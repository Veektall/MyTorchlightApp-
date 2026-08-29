#!/usr/bin/env python3
import argparse,csv,json,math,random
from pathlib import Path
import numpy as np, torch
import torch.nn.functional as F
from torch.utils.data import Dataset,DataLoader,WeightedRandomSampler
from temporal_policy_model import load_clip,Stage8Policy,ACTIONS,ACTION_TO_ID

class Clips(Dataset):
    def __init__(self,root,rows): self.root=Path(root);self.rows=rows
    def __len__(self): return len(self.rows)
    def __getitem__(self,i):
        r=self.rows[i];return load_clip(self.root/r['context_clip_path']),ACTION_TO_ID[r['action']],r

def split_by_class_time(rows):
    tr=[];va=[]
    for a in ACTIONS:
        s=sorted([r for r in rows if r['action']==a],key=lambda r:float(r['action_time_sec']))
        n=max(1,int(round(len(s)*.2))) if len(s)>1 else 1
        va.extend(s[-n:]);tr.extend(s[:-n])
    return sorted(tr,key=lambda r:float(r['action_time_sec'])),sorted(va,key=lambda r:float(r['action_time_sec']))

def metrics(y,p):
    cm=np.zeros((len(ACTIONS),len(ACTIONS)),dtype=int)
    for a,b in zip(y,p):cm[a,b]+=1
    recalls=[]
    for i in range(len(ACTIONS)):
        d=cm[i].sum();recalls.append(cm[i,i]/d if d else float('nan'))
    acc=float((np.array(y)==np.array(p)).mean()) if y else 0.0
    bal=float(np.nanmean(recalls))
    return acc,bal,cm,recalls

def evaluate(m,loader,device):
    m.eval();ys=[];ps=[];rows=[]
    with torch.no_grad():
        for x,y,r in loader:
            q=m(x.to(device)).softmax(1).cpu();pred=q.argmax(1)
            ys+=y.tolist();ps+=pred.tolist()
            for i in range(len(y)):rows.append((r['example_id'][i].item() if hasattr(r['example_id'][i],'item') else int(r['example_id'][i]),ACTIONS[int(y[i])],ACTIONS[int(pred[i])],float(q[i,pred[i]])))
    return ys,ps,rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--epochs',type=int,default=36);a=ap.parse_args();root=Path(a.root)
    random.seed(23);np.random.seed(23);torch.manual_seed(23)
    rows=[json.loads(x) for x in (root/'stage6_actions.jsonl').read_text().splitlines() if x.strip()];train,val=split_by_class_time(rows)
    if any(sum(r['action']==x for r in train)==0 for x in ACTIONS):raise SystemExit('training split lost an action class')
    ds=Clips(root,train);counts={x:sum(r['action']==x for r in train) for x in ACTIONS};weights=[1.0/counts[r['action']] for r in train]
    sampler=WeightedRandomSampler(weights,num_samples=max(len(train),100),replacement=True);tl=DataLoader(ds,batch_size=12,sampler=sampler,num_workers=0);vl=DataLoader(Clips(root,val),batch_size=12,shuffle=False,num_workers=0)
    device='cuda' if torch.cuda.is_available() else 'cpu';m=Stage8Policy().to(device);ck=torch.load(root/'stage7_temporal_encoder.pt',map_location='cpu');m.encoder.load_state_dict(ck['encoder']);opt=torch.optim.AdamW(m.parameters(),lr=8e-4,weight_decay=2e-4)
    hist=[]
    for ep in range(a.epochs):
        m.train();ls=[]
        for x,y,_ in tl:
            x=x.to(device);y=y.to(device);logits=m(x);loss=F.cross_entropy(logits,y,label_smoothing=.03);opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),2.0);opt.step();ls.append(loss.item())
        hist.append(sum(ls)/len(ls))
    y,p,pred_rows=evaluate(m,vl,device);acc,bal,cm,recalls=metrics(y,p)
    majority=max(range(len(ACTIONS)),key=lambda i:sum(int(v==i) for v in y));majority_acc=sum(int(v==majority) for v in y)/len(y)
    torch.save({'model':m.state_dict(),'actions':ACTIONS,'input_size':[8,3,54,96],'stage7_init':True,'seed':23},root/'stage8_imitation_policy.pt')
    with open(root/'stage8_predictions.csv','w',newline='') as f:
        w=csv.writer(f);w.writerow(['example_id','true_action','pred_action','pred_confidence']);w.writerows(pred_rows)
    summary={'stage':'8-balanced-imitation-policy-v1','examples_total':len(rows),'train_examples':len(train),'validation_examples':len(val),'train_counts':counts,'validation_counts':{x:sum(r['action']==x for r in val) for x in ACTIONS},'epochs':a.epochs,'device':device,'initialized_from_stage7':True,'balanced_sampling':True,'validation_split':'latest examples within each action class','validation_accuracy':round(acc,4),'validation_balanced_accuracy':round(bal,4),'majority_baseline_accuracy':round(majority_acc,4),'per_class_recall':{ACTIONS[i]:(None if math.isnan(recalls[i]) else round(recalls[i],4)) for i in range(len(ACTIONS))},'confusion_matrix':cm.tolist(),'privileged_game_state_used':False,'status':'complete','interpretation':'Pipeline proof only; one 51s trajectory and severe original class imbalance are insufficient evidence of a competent general policy.'}
    (root/'stage8_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
    if len(rows)<20 or len(val)<5 or any(sum(r['action']==x for r in val)==0 for x in ACTIONS) or not math.isfinite(acc):raise SystemExit(9)
if __name__=='__main__':main()
