#!/usr/bin/env python3
import argparse, json, random, copy
from collections import Counter
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from stage10_v4_model import ACTIONS, ACTION_TO_ID, Stage10Policy

VAL_EPISODES={'official_stage10_ep04','official_stage10_ep08'}

class Clips(Dataset):
    def __init__(self,x,y): self.x=x; self.y=y
    def __len__(self): return len(self.x)
    def __getitem__(self,i):
        t=torch.from_numpy(self.x[i]).float().permute(0,3,1,2)/255.0
        return t,int(self.y[i])

def read_rgb8(path):
    a=np.fromfile(path,dtype=np.uint8)
    if a.size!=8*54*96*3: raise RuntimeError(f'bad rgb8 {path}: {a.size}')
    return a.reshape(8,54,96,3)

def metrics(model,x,y):
    model.eval(); pred=[]; conf=[]
    with torch.no_grad():
        for xb,yb in DataLoader(Clips(x,y),batch_size=64,shuffle=False):
            pr=model(xb).softmax(1); pred.extend(pr.argmax(1).tolist()); conf.extend(pr.max(1).values.tolist())
    cm=np.zeros((5,5),dtype=int)
    for a,b in zip(y,pred): cm[int(a),int(b)]+=1
    rec=[cm[i,i]/cm[i].sum() if cm[i].sum() else float('nan') for i in range(5)]
    acc=float(np.mean(np.asarray(pred)==np.asarray(y))); bal=float(np.nanmean(rec));
    return {'accuracy':acc,'balanced_accuracy':bal,'recall':rec,'confusion_matrix':cm.tolist(),'mean_confidence':float(np.mean(conf))}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base-root',required=True);ap.add_argument('--failure-root',required=True);ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True);ap.add_argument('--epochs',type=int,default=24);args=ap.parse_args()
    random.seed(113);np.random.seed(113);torch.manual_seed(113);torch.set_num_threads(max(1,min(4,torch.get_num_threads())))
    base=Path(args.base_root);fail=Path(args.failure_root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(x) for x in (base/'stage10_examples.jsonl').read_text().splitlines() if x.strip()]
    fr=[json.loads(x) for x in (fail/'stage12_failure_examples.jsonl').read_text().splitlines() if x.strip() and json.loads(x).get('eligible_for_retraining')]
    if len(fr)<80: raise SystemExit(f'insufficient Stage-12 correction buffer: {len(fr)}')
    train_rows=[r for r in rows if r['episode_id'] not in VAL_EPISODES]; val_rows=[r for r in rows if r['episode_id'] in VAL_EPISODES]
    def load_base(rs):
        x=np.stack([read_rgb8(base/r['example_path']) for r in rs]);y=np.array([ACTION_TO_ID[r['action']] for r in rs],dtype=np.int64);return x,y
    xtr,ytr=load_base(train_rows);xv,yv=load_base(val_rows)
    xf=np.stack([read_rgb8(f/r['example_path']) for r in fr]);yf=np.array([ACTION_TO_ID[r['teacher_action']] for r in fr],dtype=np.int64)
    ck=torch.load(args.checkpoint,map_location='cpu');model=Stage10Policy();model.load_state_dict(ck['model'])
    before_val=metrics(model,xv,yv);before_fail=metrics(model,xf,yf)
    x=np.concatenate([xtr,xf],0);y=np.concatenate([ytr,yf],0);source=np.concatenate([np.zeros(len(xtr),dtype=np.int64),np.ones(len(xf),dtype=np.int64)])
    counts=np.bincount(y,minlength=5);w=np.array([(1.0/max(counts[int(y[i])],1))*(2.5 if source[i] else 1.0) for i in range(len(y))],dtype=np.float64)
    sampler=WeightedRandomSampler(w,num_samples=max(1800,len(y)*3),replacement=True);dl=DataLoader(Clips(x,y),batch_size=32,sampler=sampler)
    opt=torch.optim.AdamW(model.parameters(),lr=6e-4,weight_decay=1e-4)
    best=None;best_state=None;best_pack=None;patience=0
    for ep in range(args.epochs):
        model.train();losses=[]
        for xb,yb in dl:
            loss=F.cross_entropy(model(xb),yb,label_smoothing=.01);opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),2);opt.step();losses.append(loss.item())
        vm=metrics(model,xv,yv);fm=metrics(model,xf,yf);min_man=min(vm['recall'][1:]);score=vm['balanced_accuracy']+.30*fm['accuracy']+.15*min_man
        if best is None or score>best+1e-5: best=score;best_state=copy.deepcopy(model.state_dict());best_pack=(ep+1,vm,fm,float(np.mean(losses)));patience=0
        else: patience+=1
        print(json.dumps({'epoch':ep+1,'loss':round(float(np.mean(losses)),5),'val_bal':round(vm['balanced_accuracy'],4),'failure_acc':round(fm['accuracy'],4),'min_maneuver_recall':round(min_man,4)}),flush=True)
        if patience>=7: break
    model.load_state_dict(best_state);best_epoch,after_val,after_fail,last_loss=best_pack
    majority=float(np.bincount(yv,minlength=5).max()/len(yv));gain=after_fail['accuracy']-before_fail['accuracy'];min_man=float(min(after_val['recall'][1:]))
    accepted=bool(after_val['accuracy']>majority and after_val['accuracy']>=before_val['accuracy']-.05 and after_val['balanced_accuracy']>=.50 and after_val['balanced_accuracy']>=before_val['balanced_accuracy']-.06 and min_man>=.30 and (gain>=.03 or after_fail['accuracy']>=.80))
    summary={'stage':'13-targeted-failure-correction-v1','policy_contract':'pixel-policy-contract-v1.1','base_exact_examples':len(rows),'base_train_examples':len(train_rows),'held_out_exact_examples':len(val_rows),'held_out_episode_ids':sorted(VAL_EPISODES),'stage12_correction_examples':len(fr),'correction_teacher_action_counts':dict(Counter(r['teacher_action'] for r in fr)),'correction_reason_counts':dict(Counter(r['buffer_reason'] for r in fr)),'correction_label_origin':'stage12_pixel_teacher_correction','post_action_pixels_used':False,'privileged_game_state_used':False,'initial_checkpoint':str(args.checkpoint),'best_epoch':best_epoch,'before':{'heldout':before_val,'failure_buffer':before_fail},'after':{'heldout':after_val,'failure_buffer':after_fail},'failure_buffer_accuracy_gain':round(gain,4),'heldout_majority_accuracy':round(majority,4),'min_maneuver_recall':round(min_man,4),'acceptance_gate':{'heldout_accuracy_above_majority':True,'heldout_accuracy_max_regression':.05,'heldout_balanced_accuracy_min':.50,'heldout_balanced_accuracy_max_regression':.06,'maneuver_recall_min':.30,'failure_buffer_accuracy_gain_min_or_absolute':[.03,.80]},'accepted':accepted}
    for key in ['before','after']:
        for sub in summary[key].values():
            sub['accuracy']=round(sub['accuracy'],4);sub['balanced_accuracy']=round(sub['balanced_accuracy'],4);sub['recall']=[round(float(v),4) for v in sub['recall']];sub['mean_confidence']=round(sub['mean_confidence'],4)
    (out/'stage13_summary.json').write_text(json.dumps(summary,indent=2));torch.save({'model':model.state_dict(),'actions':ACTIONS,'input_size':[8,3,54,96],'policy_contract':'pixel-policy-contract-v1.1','stage':'13-targeted-failure-correction-v1','best_epoch':best_epoch},out/'stage13_policy.pt');print(json.dumps(summary,indent=2),flush=True)
    if not accepted: raise SystemExit(31)
if __name__=='__main__': main()
