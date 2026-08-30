#!/usr/bin/env python3
import argparse,json,random
from pathlib import Path
from collections import Counter
import numpy as np,torch
import torch.nn.functional as F
from torch.utils.data import DataLoader,WeightedRandomSampler
from stage10_v4_model import Stage10Policy,ACTIONS,ACTION_TO_ID
from train_stage10_v4 import MemClips,choose_split,cm_metrics

def load_rows(root,rows):
    X=np.empty((len(rows),8,54,96,3),dtype=np.uint8);Y=np.empty(len(rows),dtype=np.int64)
    for i,r in enumerate(rows):X[i]=np.fromfile(root/r['example_path'],dtype=np.uint8).reshape(8,54,96,3);Y[i]=ACTION_TO_ID[r['action']]
    return torch.from_numpy(X),torch.from_numpy(Y)
def evaluate(m,X,Y,idx):
    m.eval();y=[];p=[]
    with torch.no_grad():
        for x,t,_ in DataLoader(MemClips(X[idx],Y[idx]),batch_size=32,shuffle=False):y+=t.tolist();p+=m(x).argmax(1).tolist()
    return cm_metrics(y,p)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--epochs',type=int,default=14);args=ap.parse_args();root=Path(args.root);random.seed(91);np.random.seed(91);torch.manual_seed(91)
    base=[json.loads(x) for x in (root/'stage10_examples.jsonl').read_text().splitlines() if x.strip()];corr=[json.loads(x) for x in (root/'stage12_corrections.jsonl').read_text().splitlines() if x.strip()]
    if len(corr)<10:raise SystemExit(31)
    tr,va,val_ids=choose_split(base);trset={r['example_path'] for r in tr};vaset={r['example_path'] for r in va};Xb,Yb=load_rows(root,base);idxtr=np.array([i for i,r in enumerate(base) if r['example_path'] in trset]);idxva=np.array([i for i,r in enumerate(base) if r['example_path'] in vaset]);Xc,Yc=load_rows(root,corr)
    ck=torch.load(root/'stage10_imitation_policy.pt',map_location='cpu');m=Stage10Policy();m.load_state_dict(ck['model']);before=evaluate(m,Xb,Yb,idxva);X=torch.cat([Xb[idxtr],Xc]);Y=torch.cat([Yb[idxtr],Yc]);base_n=len(idxtr);counts=np.bincount(Y.numpy(),minlength=5);w=[]
    for i,y in enumerate(Y.tolist()):w.append((2.5 if i>=base_n else 1.0)/max(1,counts[y]))
    samp=WeightedRandomSampler(w,num_samples=max(420,len(Y)),replacement=True);dl=DataLoader(MemClips(X,Y),batch_size=24,sampler=samp);opt=torch.optim.AdamW(m.parameters(),lr=4e-4,weight_decay=2e-4)
    for _ in range(args.epochs):
        m.train()
        for x,y,_ in dl:
            loss=F.cross_entropy(m(x),y,label_smoothing=.02);opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),2);opt.step()
    after=evaluate(m,Xb,Yb,idxva);acc0,bal0,cm0,rec0=before;acc1,bal1,cm1,rec1=after;accepted=bal1>=bal0-.02 and all(rec1[i]>=.20 for i in range(5))
    torch.save({'model':m.state_dict(),'actions':ACTIONS,'input_size':[8,3,54,96],'policy_contract':'pixel-policy-contract-v1.1','stage':'12-corrective-v1'},root/'stage12_corrected_policy.pt')
    out={'stage':'12-corrective-finetune-v1','correction_examples':len(corr),'correction_counts':dict(Counter(r['action'] for r in corr)),'validation_episode_ids':val_ids,'before':{'accuracy':round(acc0,4),'balanced_accuracy':round(bal0,4),'recall':{ACTIONS[i]:round(float(rec0[i]),4) for i in range(5)}},'after':{'accuracy':round(acc1,4),'balanced_accuracy':round(bal1,4),'recall':{ACTIONS[i]:round(float(rec1[i]),4) for i in range(5)}},'acceptance_gate':{'balanced_accuracy_no_regression_more_than':.02,'all_class_recall_min':.20},'privileged_game_state_used':False,'accepted':accepted};(root/'stage12_train_summary.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2));raise SystemExit(0 if accepted else 32)
if __name__=='__main__':main()
