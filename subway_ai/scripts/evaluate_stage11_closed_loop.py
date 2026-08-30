#!/usr/bin/env python3
import argparse, io, json, time
from collections import Counter, deque
from pathlib import Path

import numpy as np
from PIL import Image
import torch
from playwright.sync_api import sync_playwright

from stage10_v4_model import ACTIONS, Stage10Policy

W,H=96,54
KEYS={'left':'ArrowLeft','right':'ArrowRight','jump':'ArrowUp','roll':'ArrowDown'}
BROWSER_ARGS=['--autoplay-policy=no-user-gesture-required','--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox','--window-size=1280,720']

def decode_png(png):
    im=Image.open(io.BytesIO(png)).convert('RGB').resize((W,H),Image.Resampling.BILINEAR)
    rgb=np.asarray(im,dtype=np.uint8)
    gray=(.299*rgb[...,0]+.587*rgb[...,1]+.114*rgb[...,2]).astype(np.float32)/255.0
    return rgb,gray

def mean_abs(a,b): return float(np.abs(a-b).mean())
def median(xs): return float(np.median(xs)) if xs else 0.0

def is_death(rgb):
    x=rgb.astype(np.float32)/255.0; h,w,_=x.shape
    lower=x[int(h*.5):]
    green=((lower[...,1]>lower[...,0]*1.12)&(lower[...,1]>lower[...,2]*1.25)&(lower[...,1]>.38)).mean()
    orange=((x[...,0]>.68)&(x[...,1]>.20)&(x[...,1]<.78)&(x[...,2]<.28)).mean()
    return bool(green>.48 and orange>.10)

def zone_risk(gray,prev,xa,xb,ya,yb):
    h,w=gray.shape;x0=int(w*xa);x1=max(x0+2,int(w*xb));y0=int(h*ya);y1=max(y0+2,int(h*yb));r=gray[y0:y1,x0:x1]
    if r.size<4:return 0.0
    edge=.5*(np.abs(np.diff(r,axis=1)).mean()+np.abs(np.diff(r,axis=0)).mean())
    temp=float(np.abs(r-prev[y0:y1,x0:x1]).mean()) if prev is not None else 0.0
    return float(1.15*edge+.75*temp+.12*r.std())

def lane_danger(gray,prev):
    return [zone_risk(gray,prev,a,b,.38,.90) for a,b in [(.12,.40),(.34,.66),(.60,.88)]]

class RunningRisk:
    def __init__(self):self.n=0;self.muU=0.;self.muL=0.;self.vU=.0025;self.vL=.0025
    def z(self,u,l):
        if self.n<6:return 0.,0.
        return (u-self.muU)/max(self.vU,1e-5)**.5,(l-self.muL)/max(self.vL,1e-5)**.5
    def update(self,u,l):
        a=.18 if self.n<12 else .06
        if self.n==0:self.muU=u;self.muL=l
        du=u-self.muU;dl=l-self.muL;self.muU+=a*du;self.muL+=a*dl;self.vU=(1-a)*self.vU+a*du*du;self.vL=(1-a)*self.vL+a*dl*dl;self.n+=1

class CorridorPolicy:
    def __init__(self):self.lane=1;self.last={};self.stats=RunningRisk()
    def act(self,gray,prev,t):
        d=lane_danger(gray,prev);best=int(np.argmin(d));cur=d[self.lane];a,b=[(.12,.40),(.34,.66),(.60,.88)][self.lane]
        upper=zone_risk(gray,prev,a,b,.20,.55);lower=zone_risk(gray,prev,a,b,.55,.92);zu,zl=self.stats.z(upper,lower);self.stats.update(upper,lower)
        lateral=t-self.last.get('left',-99)>.55 and t-self.last.get('right',-99)>.55
        action='stay'
        if lateral and best!=self.lane and cur-d[best]>.014:action='left' if best<self.lane else 'right'
        elif t-self.last.get('roll',-99)>.90 and zu>.35 and zu>zl+.18:action='roll'
        elif t-self.last.get('jump',-99)>.72 and zl>.35 and zl>zu+.10:action='jump'
        elif t-self.last.get('jump',-99)>.80 and cur>float(np.median(d))+.022:action='jump'
        self.last[action]=t
        if action=='left':self.lane=max(0,self.lane-1)
        elif action=='right':self.lane=min(2,self.lane+1)
        return action,1.0

class LearnedPolicy:
    def __init__(self,checkpoint):
        self.model=Stage10Policy();ck=torch.load(checkpoint,map_location='cpu');self.model.load_state_dict(ck['model']);self.model.eval();self.last={}
    def act(self,ring,t):
        if len(ring)<8:return 'stay',1.0
        x=np.stack(ring).astype(np.float32)/255.0;x=torch.from_numpy(x).permute(0,3,1,2).unsqueeze(0)
        with torch.no_grad():pr=self.model(x).softmax(1)[0]
        order=torch.argsort(pr,descending=True).tolist()
        cooldown={'left':.45,'right':.45,'jump':.58,'roll':.68,'stay':0.0}
        chosen='stay'
        for i in order:
            a=ACTIONS[i]
            if t-self.last.get(a,-99)>=cooldown[a]:chosen=a;break
        self.last[chosen]=t
        return chosen,float(pr[ACTIONS.index(chosen)])

def focus_canvas(canvas):
    canvas.evaluate("c=>{c.tabIndex=0;c.focus()}")
    b=canvas.bounding_box()
    if b:
        try: canvas.click(position={'x':b['width']/2,'y':b['height']/2},force=True)
        except Exception: pass

def open_game(browser,episode_id):
    context=browser.new_context(viewport={'width':1280,'height':720},locale='en-US');page=context.new_page();page.goto('https://poki.com/en/g/subway-surfers',wait_until='domcontentloaded',timeout=120000)
    deadline=time.time()+100;game=None;canvas=None
    while time.time()<deadline:
        fs=[f for f in page.frames if '.gdn.poki.com' in f.url]
        if fs:
            game=fs[-1];c=game.locator('#pixi-canvas')
            if c.count():canvas=c;break
        time.sleep(.65)
    if canvas is None:context.close();raise RuntimeError('official Pixi canvas not found')
    webgl=game.evaluate("""()=>{const c=document.createElement('canvas');const gl=c.getContext('webgl',{stencil:true,failIfMajorPerformanceCaveat:true});if(!gl)return{ok:false};const e=gl.getExtension('WEBGL_debug_renderer_info');return{ok:true,stencil:gl.getParameter(gl.STENCIL_BITS),renderer:e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)}}""")
    if not webgl.get('ok'):context.close();raise RuntimeError('strict WebGL gate failed')
    focus_canvas(canvas);return context,page,canvas,webgl

def activity(canvas,n=7,spacing=.18):
    frames=[];deaths=[]
    for i in range(n):
        rgb,g=decode_png(canvas.screenshot());frames.append(g);deaths.append(is_death(rgb));
        if i+1<n:time.sleep(spacing)
    ds=[mean_abs(frames[i-1],frames[i]) for i in range(1,len(frames))];med=median(ds);active=sum(x>.0045 for x in ds);strong=sum(x>.010 for x in ds)
    return {'ok':not deaths[-1] and (med>.003 or active>=3 or strong>=2),'median_motion':round(med,6),'active_pairs':active,'strong_pairs':strong,'death_at_end':deaths[-1]}

def harden_startup(canvas):
    seqs=[['Space','Enter','Space','ArrowUp'],['Enter','Space','ArrowLeft','ArrowRight','ArrowUp'],['Space','ArrowUp','Space','ArrowDown'],['ArrowUp','ArrowLeft','ArrowRight','Space']]
    for r in range(10):
        focus_canvas(canvas);s=activity(canvas)
        if s['ok']:return s
        for k in seqs[r%len(seqs)]:canvas.press(k,delay=180);time.sleep(.28)
        time.sleep(.55);s=activity(canvas,8,.19)
        if s['ok']:return s
    return {'ok':False}

def run_episode(browser,policy_name,episode_index,checkpoint,max_sec):
    context,page,canvas,webgl=open_game(browser,f'{policy_name}-{episode_index}')
    try:
        start=harden_startup(canvas)
        if not start.get('ok'):return {'policy':policy_name,'episode':episode_index,'valid':False,'reason':'startup_failed'}
        corridor=CorridorPolicy() if policy_name=='corridor_cv' else None
        learned=LearnedPolicy(checkpoint) if policy_name=='learned' else None
        ring=deque(maxlen=8);prev=None;last_jump=-99.;actions=[];conf=[];dead=False;t0=time.time();last_dec=-99.
        while time.time()-t0<max_sec:
            rgb,gray=decode_png(canvas.screenshot());t=time.time()-t0
            if is_death(rgb):dead=True;break
            ring.append(rgb)
            action='stay';c=1.0
            if t-last_dec>=.26:
                if policy_name=='stay': action='stay'
                elif policy_name=='always_jump':
                    action='jump' if t-last_jump>=.82 else 'stay'
                    if action=='jump':last_jump=t
                elif policy_name=='corridor_cv':action,c=corridor.act(gray,prev,t)
                elif policy_name=='learned':action,c=learned.act(ring,t)
                else:raise ValueError(policy_name)
                if action!='stay':canvas.press(KEYS[action],delay=180)
                actions.append(action);conf.append(c);last_dec=t
            prev=gray;time.sleep(.055)
        dur=time.time()-t0;cnt=Counter(actions)
        return {'policy':policy_name,'episode':episode_index,'valid':True,'survival_sec':round(dur,3),'death_detected':dead,'censored_at_cap':not dead and dur>=max_sec-.5,'action_counts':{a:cnt[a] for a in ACTIONS},'actions_per_sec':round(len(actions)/max(dur,1e-6),3),'mean_confidence':round(float(np.mean(conf)),4) if conf else None,'webgl':webgl,'score_metric_available':False,'distance_metric_available':False,'policy_input':'pixels_only_8_rgb_frames' if policy_name=='learned' else 'pixels_or_time_baseline'}
    finally:context.close()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True);ap.add_argument('--episodes',type=int,default=2);ap.add_argument('--max-seconds',type=float,default=28);args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=BROWSER_ARGS)
        try:
            for pol in ['stay','always_jump','corridor_cv','learned']:
                for ep in range(1,args.episodes+1):
                    try:r=run_episode(browser,pol,ep,args.checkpoint,args.max_seconds)
                    except Exception as e:r={'policy':pol,'episode':ep,'valid':False,'reason':str(e)}
                    results.append(r);print(json.dumps(r),flush=True)
        finally:browser.close()
    stats={}
    for pol in ['stay','always_jump','corridor_cv','learned']:
        rr=[r for r in results if r.get('policy')==pol and r.get('valid')]
        ss=[r['survival_sec'] for r in rr]
        stats[pol]={'valid_episodes':len(rr),'mean_survival_sec':round(float(np.mean(ss)),3) if ss else None,'median_survival_sec':round(float(np.median(ss)),3) if ss else None,'deaths':sum(bool(r.get('death_detected')) for r in rr),'mean_actions_per_sec':round(float(np.mean([r['actions_per_sec'] for r in rr])),3) if rr else None}
    valid=all(stats[p]['valid_episodes']>=args.episodes for p in stats)
    learned=stats['learned']['mean_survival_sec'];cheap=[stats['stay']['mean_survival_sec'],stats['always_jump']['mean_survival_sec']]
    beats_cheap=bool(valid and learned is not None and all(x is not None and learned>x for x in cheap))
    summary={'stage':'11-official-closed-loop-benchmark-v1','policy_contract':'pixel-policy-contract-v1.1','official_game':'https://poki.com/en/g/subway-surfers','episodes_per_policy':args.episodes,'max_seconds_per_episode':args.max_seconds,'results':results,'aggregate':stats,'benchmark_complete':valid,'learned_beats_both_cheap_baselines':beats_cheap,'competence_claim':beats_cheap and (stats['corridor_cv']['mean_survival_sec'] is None or learned>=.8*stats['corridor_cv']['mean_survival_sec']),'score_distance_note':'Not read from game internals; unavailable here rather than violating the pixel-policy contract.'}
    (out/'stage11_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2));
    if not valid:raise SystemExit(21)
if __name__=='__main__':main()
