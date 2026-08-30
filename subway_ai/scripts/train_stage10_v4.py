#!/usr/bin/env python3
import argparse,itertools,json,random,copy
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

def coarse_rgb(x):
    # Fixed, non-learned spatial target: enough layout to make reconstruction meaningful,
    # small enough that a temporal hidden state can predict residual corrections.
    return F.adaptive_avg_pool2d(x,(6,10)).flatten(1)

def masked_reconstruction(pre,head,x,mask_index=4):
    prev=x[:,mask_index-1]; target=x[:,mask_index]; nxt=x[:,mask_index+1]
    interp=.5*(prev+nxt)
    masked=x.clone(); masked[:,mask_index]=interp
    _,h=pre.encoder(masked)
    base=coarse_rgb(interp); delta=head(h)
    pred=base+delta
    return pred,coarse_rgb(target),base,coarse_rgb(prev),interp,target

def reconstruction_eval(pre,head,loader):
    pre.eval();head.eval();model_l1=[];interp_l1=[];persist_l1=[];raw_interp=[];raw_persist=[]
    with torch.no_grad():
        for x in loader:
            pred,target,base,persist,interp,raw_target=masked_reconstruction(pre,head,x)
            model_l1.append(F.l1_loss(pred,target,reduction='mean').item())
            interp_l1.append(F.l1_loss(base,target,reduction='mean').item())
            persist_l1.append(F.l1_loss(persist,target,reduction='mean').item())
            raw_interp.append(F.l1_loss(interp,raw_target,reduction='mean').item())
            raw_persist.append(F.l1_loss(x[:,3],raw_target,reduction='mean').item())
    return {
        'model_coarse_l1':float(np.mean(model_l1)),
        'interpolation_coarse_l1':float(np.mean(interp_l1)),
        'persistence_coarse_l1':float(np.mean(persist_l1)),
        'interpolation_raw_pixel_l1':float(np.mean(raw_interp)),
        'persistence_raw_pixel_l1':float(np.mean(raw_persist)),
    }

def evaluate_policy(model,X,Y,idx):
    model.eval();yv=[];pv=[];conf=[]
    with torch.no_grad():
        for x,y,_ in DataLoader(MemClips(X[idx],Y[idx]),batch_size=32,shuffle=False):
            pr=model(x).softmax(1);pv+=pr.argmax(1).tolist();yv+=y.tolist();conf+=pr.max(1).values.tolist()
    acc,bal,cm,rec=cm_metrics(yv,pv)
    return acc,bal,cm,rec,float(np.mean(conf)) if conf else 0.0

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
    X=torch.from_numpy(X); idx_tr=np.array([i for i,p in enumerate(paths) if p in tr_ids]); idx_va=np.array([i for i,p in enumerate(paths) if p in va_ids])
    device='cpu'

    # Stage 10A v5: mask the middle observation and reconstruct it from temporal context.
    # The deterministic two-neighbour interpolation is the explicit strong baseline;
    # previous-frame persistence is the cheap baseline that the signal must beat.
    pre=Stage10Pretrainer().to(device)
    head=nn.Sequential(nn.Linear(96,128),nn.ReLU(),nn.Linear(128,3*6*10)).to(device)
    nn.init.zeros_(head[-1].weight);nn.init.zeros_(head[-1].bias)
    opt=torch.optim.AdamW(list(pre.encoder.parameters())+list(head.parameters()),lr=8e-4,weight_decay=1e-4)
    dl=DataLoader(MemClips(X[idx_tr]),batch_size=32,shuffle=True,num_workers=0)
    vl=DataLoader(MemClips(X[idx_va]),batch_size=32,shuffle=False,num_workers=0)
    best=None;best_state=None;patience=0
    for ep in range(args.pretrain_epochs):
        pre.train();head.train();ls=[]
        for x in dl:
            pred,target,base,_,_,_=masked_reconstruction(pre,head,x)
            # Residual reconstruction starts exactly at interpolation; Huber keeps
            # occasional fast-scene changes from dominating this small corpus.
            loss=F.smooth_l1_loss(pred,target,beta=.03)
            opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(list(pre.encoder.parameters())+list(head.parameters()),2);opt.step();ls.append(loss.item())
        m=reconstruction_eval(pre,head,vl)
        score=m['model_coarse_l1']
        if best is None or score<best-1e-5:
            best=score;best_state=(copy.deepcopy(pre.encoder.state_dict()),copy.deepcopy(head.state_dict()),ep+1,m);patience=0
        else:patience+=1
        if ep in {0,args.pretrain_epochs-1} or patience==0:print('pretrain epoch',ep+1,'loss',float(np.mean(ls)),'val_l1',score,flush=True)
        if patience>=5:break
    pre.encoder.load_state_dict(best_state[0]);head.load_state_dict(best_state[1]);best_epoch=best_state[2];m=best_state[3]
    raw_gain=(m['persistence_raw_pixel_l1']-m['interpolation_raw_pixel_l1'])/max(m['persistence_raw_pixel_l1'],1e-9)
    coarse_gain=(m['persistence_coarse_l1']-m['model_coarse_l1'])/max(m['persistence_coarse_l1'],1e-9)
    residual_gain=(m['interpolation_coarse_l1']-m['model_coarse_l1'])/max(m['interpolation_coarse_l1'],1e-9)
    # The masked temporal signal must materially beat persistence. The learned
    # residual may tie the already-strong interpolation baseline, but cannot erase it.
    pre_ok=raw_gain>=.08 and coarse_gain>=.08 and m['model_coarse_l1']<=m['interpolation_coarse_l1']*1.01
    temporal={
        'stage':'10A-masked-temporal-reconstruction-v5','train_examples':len(idx_tr),'validation_examples':len(idx_va),'validation_episode_ids':val_ids,'best_epoch':best_epoch,
        'masked_frame_index':4,'objective':'reconstruct masked middle frame as learned residual over two-neighbour interpolation','target_representation':'fixed 6x10 RGB spatial grid',
        'validation':{k:round(v,6) for k,v in m.items()},
        'raw_interpolation_improvement_over_persistence':round(raw_gain,4),'learned_coarse_improvement_over_persistence':round(coarse_gain,4),'learned_residual_improvement_over_interpolation':round(residual_gain,4),
        'acceptance_gate':{'raw_interpolation_improvement_over_persistence_min':.08,'learned_coarse_improvement_over_persistence_min':.08,'learned_model_may_not_degrade_interpolation_by_more_than':.01},
        'policy_labels_used':False,'privileged_game_state_used':False,'accepted':pre_ok}
    (root/'stage10_temporal_summary.json').write_text(json.dumps(temporal,indent=2));torch.save({'encoder':pre.encoder.state_dict(),'policy_contract':'pixel-policy-contract-v1.1','objective':'masked_temporal_reconstruction_v5','best_epoch':best_epoch},root/'stage10_temporal_encoder.pt');print(json.dumps(temporal,indent=2),flush=True)
    if not pre_ok:raise SystemExit(13)

    # Stage 10B: semantic imitation policy with validation-time model selection.
    policy=Stage10Policy();policy.encoder.load_state_dict(pre.encoder.state_dict());opt=torch.optim.AdamW(policy.parameters(),lr=8e-4,weight_decay=2e-4)
    tr_counts=np.bincount(Y[idx_tr],minlength=5);weights=np.array([1.0/tr_counts[Y[i]] for i in idx_tr],dtype=np.float64);sampler=WeightedRandomSampler(weights,num_samples=max(len(idx_tr),384),replacement=True)
    pdl=DataLoader(MemClips(X[idx_tr],Y[idx_tr]),batch_size=24,sampler=sampler,num_workers=0)
    best_score=-1e9;best_policy=None;best_metrics=None;best_policy_epoch=0;patience=0
    for ep in range(args.policy_epochs):
        policy.train();ls=[]
        for x,y,_ in pdl:
            logits=policy(x);loss=F.cross_entropy(logits,y,label_smoothing=.02);opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(policy.parameters(),2);opt.step();ls.append(loss.item())
        acc,bal,cm,rec,mean_conf=evaluate_policy(policy,X,Y,idx_va)
        finite_rec=[0.0 if np.isnan(r) else float(r) for r in rec]
        score=bal+.20*min(finite_rec[1:])+.08*acc
        if score>best_score+1e-5:
            best_score=score;best_policy=copy.deepcopy(policy.state_dict());best_metrics=(acc,bal,cm,rec,mean_conf);best_policy_epoch=ep+1;patience=0
        else:patience+=1
        if ep in {0,7,15,args.policy_epochs-1} or patience==0:print('policy epoch',ep+1,'loss',float(np.mean(ls)),'val_acc',acc,'val_bal',bal,flush=True)
        if ep>=15 and patience>=8:break
    policy.load_state_dict(best_policy);acc,bal,cm,rec,mean_conf=best_metrics
    vc=np.bincount(Y[idx_va].numpy(),minlength=5);maj=float(vc.max()/len(idx_va));recmap={ACTIONS[i]:round(float(rec[i]),4) for i in range(5)}
    maneuver_ok=all(rec[i]>=.30 for i in [1,2,3,4]);stay_ok=rec[0]>=.25;accepted=acc>maj and bal>=.40 and maneuver_ok and stay_ok
    summary={'stage':'10B-semantic-imitation-policy-v5','examples_total':len(rows),'train_examples':len(idx_tr),'validation_examples':len(idx_va),'validation_episode_ids':val_ids,'best_epoch':best_policy_epoch,'class_counts':dict(counts),'accuracy':round(acc,4),'balanced_accuracy':round(bal,4),'majority_accuracy':round(maj,4),'per_class_recall':recmap,'mean_prediction_confidence':round(mean_conf,4),'confusion_matrix':cm.tolist(),'acceptance_gate':{'accuracy_must_exceed_majority':True,'balanced_accuracy_min':.40,'maneuver_recall_min':.30,'stay_recall_min':.25},'label_origin':'exact_browser_input_from_semantic_pixel_teacher','privileged_game_state_used':False,'accepted':accepted}
    (root/'stage10_policy_summary.json').write_text(json.dumps(summary,indent=2));torch.save({'model':policy.state_dict(),'actions':ACTIONS,'input_size':[8,3,54,96],'policy_contract':'pixel-policy-contract-v1.1','stage':'10B-v5','best_epoch':best_policy_epoch},root/'stage10_imitation_policy.pt');print(json.dumps(summary,indent=2),flush=True)
    if not accepted:raise SystemExit(14)
if __name__=='__main__':main()
