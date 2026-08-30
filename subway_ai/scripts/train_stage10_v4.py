#!/usr/bin/env python3
import argparse,itertools,json,math,random
from collections import Counter
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import Dataset,DataLoader,WeightedRandomSampler
from stage10_v4_model import ACTIONS,ACTION_TO_ID,Stage10Pretrainer,Stage10Policy

class MemClips(Dataset):
    def __init__(self,x,y=None): self.x=x; self.y=y
    def __len__(self): return len(self.x)
    def __getitem__(self,i):
        a=self.x[i].float().permute(0,3,1,2)/255.0
        return a if self.y is None else (a,int(self.y[i]),i)

def choose_split(rows,frac=.25):
    eps=sorted({r['episode_id'] for r in rows}); total=Counter(r['action'] for r in rows); k=max(2,round(len(eps)*frac)); k=min(k,len(eps)-2); best=None
    for combo in itertools.combinations(eps,k):
        v=set(combo); tr=[r for r in rows if r['episode_id'] not in v]; va=[r for r in rows if r['episode_id'] in v];tc=Counter(r['action'] for r in tr);vc=Counter(r['action'] for r in va)
        if any(tc[a]==0 or vc[a]==0 for a in ACTIONS): continue
        score=sum(abs(vc[a]/len(va)-total[a]/len(rows)) for a in ACTIONS)+abs(len(va)/len(rows)-frac)
        cand=(score,combo,tr,va)
        if best is None or cand[:2]<best[:2]:best=cand
    if best is None: raise RuntimeError('No whole-episode split preserves all action classes')
    _,combo,tr,va=best;return tr,va,list(combo)

def cm_metrics(y,p):
    cm=np.zeros((5,5),dtype=int)
    for a,b in zip(y,p):cm[a,b]+=1
    rec=[cm[i,i]/cm[i].sum() if cm[i].sum() else float('nan') for i in range(5)]
    return float(np.mean(np.asarray(y)==np.asarray(p))),float(np.nanmean(rec)),cm,rec

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--pretrain-epochs',type=int,default=18);ap.add_argument('--policy-epochs',type=int,default=32);args=ap.parse_args()
    root=Path(args.root);random.seed(71);np.random.seed(71);torch.manual_seed(71);torch.set_num_threads(max(1,min(4,torch.get_num_threads())))
    rows=[json.loads(x) for x in (root/'stage10_examples.jsonl').read_text().splitlines() if x.strip()]
    if len({r['episode_id'] for r in rows})<6:raise SystemExit('too few episodes')
    counts=Counter(r['action'] for r in rows)
    if any(counts[a]<25 for a in ACTIONS):raise SystemExit(f'insufficient semantic labels: {counts}')
    tr_rows,va_rows,val_ids=choose_split(rows); tr_ids={r['example_path'] for r in tr_rows}; va_ids={r['example_path'] for r in va_rows}
    print('loading',len(rows),'pixel clips',flush=True)
    X=np.empty((len(rows),8,54,96,3),dtype=np.uint8);Y=np.empty(len(rows),dtype=np.int64); paths=[]
    for i,r in enumerate(rows):
        a=np.fromfile(root/r['example_path'],dtype=np.uint8)
        if a.size!=8*54*96*3:raise RuntimeError(f"bad clip {r['example_path']}: {a.size}")
        X[i]=a.reshape(8,54,96,3);Y[i]=ACTION_TO_ID[r['action']];paths.append(r['example_path'])
    X=torch.from_numpy(X); idx_tr=np.array([i for i,p in enumerate(paths) if p in tr_ids]); idx_va=np.array([i for i,p in enumerate(paths) if p in va_ids]);
    device='cpu'
    # Stage 10A: future-consistency contrastive temporal pretraining.
    pre=Stage10Pretrainer().to(device);opt=torch.optim.AdamW(pre.parameters(),lr=1.2e-3,weight_decay=1e-4)
    dl=DataLoader(MemClips(X[idx_tr]),batch_size=32,shuffle=True,num_workers=0)
    for ep in range(args.pretrain_epochs):
        pre.train();ls=[]
        for x in dl:
            x=x.to(device);h,z,dirf=pre(x);zn=torch.roll(z,1,0);pos=pre.match_logits(h,z);neg=pre.match_logits(h,zn)
            rev=torch.flip(x,[1]);hr=pre.encode_prefix(rev);dirr=pre.direction(hr)
            loss=.5*(F.binary_cross_entropy_with_logits(pos,torch.ones_like(pos))+F.binary_cross_entropy_with_logits(neg,torch.zeros_like(neg)))+.20*(F.cross_entropy(dirf,torch.zeros(len(x),dtype=torch.long))+F.cross_entropy(dirr,torch.ones(len(x),dtype=torch.long)))
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(pre.parameters(),2);opt.step();ls.append(loss.item())
        if ep in {0,args.pretrain_epochs-1}:print('pretrain epoch',ep+1,'loss',float(np.mean(ls)),flush=True)
    pre.eval();posok=negok=dirok=total=0
    vl=DataLoader(MemClips(X[idx_va]),batch_size=32,shuffle=False,num_workers=0)
    with torch.no_grad():
        for x in vl:
            h,z,df=pre(x);zn=torch.roll(z,1,0);pos=pre.match_logits(h,z);neg=pre.match_logits(h,zn);rev=torch.flip(x,[1]);dr=pre.direction(pre.encode_prefix(rev))
            posok+=int((pos>0).sum());negok+=int((neg<0).sum());dirok+=int((df.argmax(1)==0).sum())+int((dr.argmax(1)==1).sum());total+=len(x)
    future_acc=(posok+negok)/(2*total);direction_acc=dirok/(2*total);pre_ok=future_acc>=.65 and direction_acc>=.70
    temporal={'stage':'10A-future-consistency-pretraining-v4','train_examples':len(idx_tr),'validation_examples':len(idx_va),'validation_episode_ids':val_ids,'future_consistency_accuracy':round(future_acc,4),'balanced_random_candidate_baseline':.5,'forward_reversed_accuracy':round(direction_acc,4),'temporal_direction_chance_baseline':.5,'acceptance_gate':{'future_consistency_min':.65,'direction_min':.70},'policy_labels_used':False,'privileged_game_state_used':False,'accepted':pre_ok}
    (root/'stage10_temporal_summary.json').write_text(json.dumps(temporal,indent=2));torch.save({'encoder':pre.encoder.state_dict(),'policy_contract':'pixel-policy-contract-v1.1','objective':'future_candidate_consistency_plus_direction'},root/'stage10_temporal_encoder.pt');print(json.dumps(temporal,indent=2),flush=True)
    if not pre_ok:raise SystemExit(13)
    # Stage 10B: semantic imitation policy.
    policy=Stage10Policy();policy.encoder.load_state_dict(pre.encoder.state_dict());opt=torch.optim.AdamW(policy.parameters(),lr=8e-4,weight_decay=2e-4)
    tr_counts=np.bincount(Y[idx_tr],minlength=5);weights=np.array([1.0/tr_counts[Y[i]] for i in idx_tr],dtype=np.float64);sampler=WeightedRandomSampler(weights,num_samples=max(len(idx_tr),320),replacement=True)
    pdl=DataLoader(MemClips(X[idx_tr],Y[idx_tr]),batch_size=24,sampler=sampler,num_workers=0)
    for ep in range(args.policy_epochs):
        policy.train();ls=[]
        for x,y,_ in pdl:
            logits=policy(x);loss=F.cross_entropy(logits,y,label_smoothing=.02);opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(policy.parameters(),2);opt.step();ls.append(loss.item())
        if ep in {0,7,15,args.policy_epochs-1}:print('policy epoch',ep+1,'loss',float(np.mean(ls)),flush=True)
    policy.eval();yv=[];pv=[];conf=[]
    with torch.no_grad():
        for x,y,_ in DataLoader(MemClips(X[idx_va],Y[idx_va]),batch_size=32,shuffle=False):
            pr=policy(x).softmax(1);pv+=pr.argmax(1).tolist();yv+=y.tolist();conf+=pr.max(1).values.tolist()
    acc,bal,cm,rec=cm_metrics(yv,pv);vc=np.bincount(np.asarray(yv),minlength=5);maj=float(vc.max()/len(yv));recmap={ACTIONS[i]:round(float(rec[i]),4) for i in range(5)}
    maneuver_ok=all(rec[i]>=.30 for i in [1,2,3,4]);stay_ok=rec[0]>=.25;accepted=acc>maj and bal>=.40 and maneuver_ok and stay_ok
    summary={'stage':'10B-semantic-imitation-policy-v4','examples_total':len(rows),'train_examples':len(idx_tr),'validation_examples':len(idx_va),'validation_episode_ids':val_ids,'class_counts':dict(counts),'accuracy':round(acc,4),'balanced_accuracy':round(bal,4),'majority_accuracy':round(maj,4),'per_class_recall':recmap,'mean_prediction_confidence':round(float(np.mean(conf)),4),'confusion_matrix':cm.tolist(),'acceptance_gate':{'accuracy_must_exceed_majority':True,'balanced_accuracy_min':.40,'maneuver_recall_min':.30,'stay_recall_min':.25},'label_origin':'exact_browser_input_from_semantic_pixel_teacher','privileged_game_state_used':False,'accepted':accepted}
    (root/'stage10_policy_summary.json').write_text(json.dumps(summary,indent=2));torch.save({'model':policy.state_dict(),'actions':ACTIONS,'input_size':[8,3,54,96],'policy_contract':'pixel-policy-contract-v1.1','stage':'10B-v4'},root/'stage10_imitation_policy.pt');print(json.dumps(summary,indent=2),flush=True)
    if not accepted:raise SystemExit(14)
if __name__=='__main__':main()
