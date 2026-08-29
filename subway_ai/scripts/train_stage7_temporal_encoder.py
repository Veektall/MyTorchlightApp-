#!/usr/bin/env python3
import argparse,json,math,random
from pathlib import Path
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset,DataLoader
from temporal_policy_model import load_clip,Stage7Pretrainer

class Clips(Dataset):
    def __init__(self,root,rows): self.root=Path(root);self.rows=rows
    def __len__(self): return len(self.rows)
    def __getitem__(self,i):
        r=self.rows[i];return load_clip(self.root/r['context_clip_path']),float(r['action_time_sec'])

def split(rows):
    s=sorted(rows,key=lambda r:float(r['action_time_sec']));n=max(1,int(round(len(s)*.2)));return s[:-n],s[-n:]

def target_luma(x):
    y=.299*x[:,7,0:1]+.587*x[:,7,1:2]+.114*x[:,7,2:3]
    return F.interpolate(y,size=(14,24),mode='bilinear',align_corners=False)

def eval_model(m,loader,device):
    m.eval();losses=[];persist=[];dirs=[]
    with torch.no_grad():
        for x,_ in loader:
            x=x.to(device); y=target_luma(x);pred,logits=m(x); losses.append(F.l1_loss(pred,y).item());dirs.append((logits.argmax(1)==0).float().mean().item())
            p=.299*x[:,6,0:1]+.587*x[:,6,1:2]+.114*x[:,6,2:3];p=F.interpolate(p,size=(14,24),mode='bilinear',align_corners=False);persist.append(F.l1_loss(p,y).item())
    return {'next_frame_l1':sum(losses)/len(losses),'persistence_l1':sum(persist)/len(persist),'forward_direction_accuracy':sum(dirs)/len(dirs)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--epochs',type=int,default=24);a=ap.parse_args();root=Path(a.root)
    random.seed(17);torch.manual_seed(17);rows=[json.loads(x) for x in (root/'stage6_actions.jsonl').read_text().splitlines() if x.strip()]
    train,val=split(rows);device='cuda' if torch.cuda.is_available() else 'cpu';m=Stage7Pretrainer().to(device);opt=torch.optim.AdamW(m.parameters(),lr=1.5e-3,weight_decay=1e-4)
    tl=DataLoader(Clips(root,train),batch_size=12,shuffle=True,num_workers=0);vl=DataLoader(Clips(root,val),batch_size=12,shuffle=False,num_workers=0)
    history=[]
    for ep in range(a.epochs):
        m.train();ls=[]
        for x,_ in tl:
            x=x.to(device);rev=torch.flip(x,[1]);xx=torch.cat([x,rev],0);direction=torch.cat([torch.zeros(len(x),dtype=torch.long),torch.ones(len(x),dtype=torch.long)]).to(device);y=target_luma(xx)
            pred,logits=m(xx);loss=F.l1_loss(pred,y)+.20*F.cross_entropy(logits,direction);opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),2.0);opt.step();ls.append(loss.item())
        history.append(sum(ls)/len(ls))
    metrics=eval_model(m,vl,device)
    ck={'encoder':m.encoder.state_dict(),'contract':'8 RGB frames -> temporal latent','input_size':[8,3,54,96],'seed':17}
    torch.save(ck,root/'stage7_temporal_encoder.pt')
    summary={'stage':'7-temporal-visual-pretraining-v1','examples_total':len(rows),'train_examples':len(train),'validation_examples':len(val),'epochs':a.epochs,'device':device,'final_train_loss':round(history[-1],6),'validation':{k:round(v,6) for k,v in metrics.items()},'objectives':['predict next-frame low-resolution luma from first 7 frames','classify forward versus reversed temporal order'],'policy_labels_used':False,'privileged_game_state_used':False,'status':'complete'}
    (root/'stage7_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
    if len(rows)<20 or not all(math.isfinite(v) for v in metrics.values()):raise SystemExit(8)
if __name__=='__main__':main()
