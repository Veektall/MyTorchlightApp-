#!/usr/bin/env python3
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

ACTIONS=['stay','left','right','jump','roll']
ACTION_TO_ID={a:i for i,a in enumerate(ACTIONS)}

def load_rgb8(path):
    a=np.fromfile(path,dtype=np.uint8)
    expected=8*54*96*3
    if a.size!=expected: raise RuntimeError(f'{path}: expected {expected} bytes, got {a.size}')
    a=a.reshape(8,54,96,3).astype(np.float32)/255.0
    return torch.from_numpy(a).permute(0,3,1,2).contiguous()

class FrameEncoder(nn.Module):
    def __init__(self,dim=64):
        super().__init__()
        self.net=nn.Sequential(
            nn.Conv2d(3,16,5,2,2),nn.ReLU(),
            nn.Conv2d(16,32,3,2,1),nn.ReLU(),
            nn.Conv2d(32,64,3,2,1),nn.ReLU(),
            nn.AdaptiveAvgPool2d(1))
        self.proj=nn.Linear(64,dim)
    def forward(self,x): return self.proj(self.net(x).flatten(1))

class TemporalEncoder(nn.Module):
    def __init__(self,frame_dim=64,hidden=96):
        super().__init__(); self.frame=FrameEncoder(frame_dim); self.gru=nn.GRU(frame_dim,hidden,batch_first=True)
    def forward(self,x):
        b,t,c,h,w=x.shape
        z=self.frame(x.reshape(b*t,c,h,w)).reshape(b,t,-1)
        seq,hid=self.gru(z); return seq,hid[-1]

def _zone(gray,prev,xa,xb,ya,yb):
    h,w=gray.shape[-2:]
    x0=max(0,int(w*xa));x1=max(x0+2,int(w*xb));y0=max(0,int(h*ya));y1=max(y0+2,int(h*yb))
    r=gray[...,y0:y1,x0:x1]; p=prev[...,y0:y1,x0:x1]
    dx=(r[...,1:]-r[...,:-1]).abs().mean((-2,-1));dy=(r[...,1:,:]-r[...,:-1,:]).abs().mean((-2,-1))
    edge=.5*(dx+dy); temp=(r-p).abs().mean((-2,-1)); std=r.flatten(-2).std(-1)
    return 1.15*edge+.75*temp+.12*std

def pixel_features(x):
    # Derived only from the 8 RGB frames; no key logs, score, coordinates or game internals.
    g=.299*x[:,:,0]+.587*x[:,:,1]+.114*x[:,:,2]; cur=g[:,-1]; prev=g[:,-2]
    lanes=[(.12,.40),(.34,.66),(.60,.88)]
    lane=[]; upper=[]; lower=[]
    for a,b in lanes:
        lane.append(_zone(cur,prev,a,b,.38,.90)); upper.append(_zone(cur,prev,a,b,.20,.55)); lower.append(_zone(cur,prev,a,b,.55,.92))
    diff=(cur-prev).abs(); bottom=diff[...,int(cur.shape[-2]*.48):,:]
    masses=[]
    for a,b in lanes:
        x0=int(cur.shape[-1]*a);x1=max(x0+1,int(cur.shape[-1]*b)); masses.append(bottom[...,x0:x1].mean((-2,-1)))
    f=torch.stack(lane+upper+lower+masses,1)
    return torch.log1p(20*f)

class Stage10Pretrainer(nn.Module):
    def __init__(self):
        super().__init__(); self.encoder=TemporalEncoder(); self.future_proj=nn.Linear(96,64); self.match=nn.Sequential(nn.Linear(64*3,96),nn.ReLU(),nn.Linear(96,1)); self.direction=nn.Linear(96,2)
    def encode_prefix(self,x): return self.encoder(x[:,:7])[1]
    def candidate(self,x8): return self.encoder.frame(x8)
    def match_logits(self,h,z):
        q=self.future_proj(h); return self.match(torch.cat([q,z,(q-z).abs()],1)).squeeze(1)
    def forward(self,x):
        h=self.encode_prefix(x); z=self.candidate(x[:,7]); return h,z,self.direction(h)

class Stage10Policy(nn.Module):
    """Pixels-only semantic action head.

    The Stage-10 temporal encoder is trained and gated separately. Held-out evidence showed
    that injecting its global hidden state into the small semantic classifier reduced
    rare-maneuver recall, because the teacher's strongest action cues are local lane/height
    hazards. Keep the action head deliberately small and auditable around those pixel cues.
    """
    def __init__(self):
        super().__init__()
        self.head=nn.Sequential(nn.Linear(12,32),nn.ReLU(),nn.Linear(32,len(ACTIONS)))
    def forward(self,x):
        return self.head(pixel_features(x))
