#!/usr/bin/env python3
import argparse,json,statistics,time
from collections import Counter,deque
from pathlib import Path
import cv2,numpy as np,torch
from playwright.sync_api import sync_playwright
from stage10_v4_model import Stage10Policy,ACTIONS
KEYS={'left':'ArrowLeft','right':'ArrowRight','jump':'ArrowUp','roll':'ArrowDown'}

def decode_png(b,w=64,h=36):
    a=cv2.imdecode(np.frombuffer(b,np.uint8),cv2.IMREAD_COLOR);rgb=cv2.cvtColor(a,cv2.COLOR_BGR2RGB);rgb=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA);g=.299*rgb[:,:,0]/255+.587*rgb[:,:,1]/255+.114*rgb[:,:,2]/255;return rgb,g

def death(rgb):
    x=rgb.astype(np.float32)/255;h,w=x.shape[:2];lo=x[int(h*.5):];green=((lo[:,:,1]>lo[:,:,0]*1.12)&(lo[:,:,1]>lo[:,:,2]*1.25)&(lo[:,:,1]>.38)).mean();orange=((x[:,:,0]>.68)&(x[:,:,1]>.20)&(x[:,:,1]<.78)&(x[:,:,2]<.28)).mean();return green>.48 and orange>.10

def band(g,prev,xa,xb,ya,yb):
    h,w=g.shape;x0,x1=int(w*xa),int(w*xb);y0,y1=int(h*ya),int(h*yb);r=g[y0:y1,x0:x1];p=prev[y0:y1,x0:x1] if prev is not None else r;edge=.5*(np.abs(np.diff(r,axis=1)).mean()+np.abs(np.diff(r,axis=0)).mean());temp=np.abs(r-p).mean();return float(1.15*edge+.75*temp+.12*r.std())
def profiles(g,prev):return [dict(upper=band(g,prev,a,b,.38,.63),lower=band(g,prev,a,b,.63,.90),full=band(g,prev,a,b,.38,.90)) for a,b in [(.12,.40),(.34,.66),(.60,.88)]]
def corridor_choose(p,lane):
    cur=p[lane];opts=[]
    if lane>0:opts.append(('left',cur['full']-p[lane-1]['full']))
    if lane<2:opts.append(('right',cur['full']-p[lane+1]['full']))
    opts.sort(key=lambda z:-z[1])
    if opts and opts[0][1]>.020:return opts[0][0]
    v=cur['lower']-cur['upper']
    if v>.012 and cur['lower']>.070:return 'jump'
    if v<-.018 and cur['upper']>.075:return 'roll'
    if opts and opts[0][1]>.010:return opts[0][0]
    return 'stay'

def open_game(p):
    browser=p.chromium.launch(headless=False,args=['--enable-webgl','--ignore-gpu-blocklist','--use-gl=angle','--use-angle=gl','--disable-dev-shm-usage','--no-sandbox','--window-size=1280,720']);ctx=browser.new_context(viewport={'width':1280,'height':720},locale='en-US');page=ctx.new_page();page.goto('https://poki.com/en/g/subway-surfers',wait_until='domcontentloaded',timeout=120000);deadline=time.time()+100;canvas=None
    while time.time()<deadline:
        frames=[f for f in page.frames if '.gdn.poki.com' in f.url]
        if frames:
            c=frames[-1].locator('#pixi-canvas')
            if c.count():canvas=c;break
        time.sleep(.5)
    if canvas is None:raise RuntimeError('official Pixi canvas not found')
    canvas.evaluate('(c)=>{c.tabIndex=0;c.focus()}')
    for r in range(10):
        imgs=[]
        for _ in range(6):imgs.append(decode_png(canvas.screenshot())[1]);time.sleep(.16)
        dif=[np.abs(imgs[i]-imgs[i-1]).mean() for i in range(1,len(imgs))]
        if np.median(dif)>.003:return browser,ctx,page,canvas
        for k in [['Space','Enter','Space','ArrowUp'],['Enter','Space','ArrowLeft','ArrowRight','ArrowUp'],['Space','ArrowUp','ArrowDown']][r%3]:canvas.press(k,delay=180);time.sleep(.25)
    raise RuntimeError('startup failed')

def model_input(buf):
    xs=[cv2.resize(rgb,(96,54),interpolation=cv2.INTER_AREA) for rgb in buf];a=np.stack(xs).astype(np.float32)/255.;return torch.from_numpy(a).permute(0,3,1,2).unsqueeze(0)

def episode(p,policy,model,max_sec,seed_index=0):
    browser,ctx,page,canvas=open_game(p);t0=time.time();buf=deque(maxlen=8);prev=None;lane=1;acts=Counter();lat=[];dead=False;steps=0
    try:
        while time.time()-t0<max_sec:
            ts=time.time();rgb,g=decode_png(canvas.screenshot())
            if death(rgb):dead=True;break
            buf.append(rgb)
            if len(buf)<8:time.sleep(.07);continue
            if policy=='stay':a='stay'
            elif policy=='periodic_jump':a='jump' if steps%7==0 else 'stay'
            elif policy=='corridor_cv':a=corridor_choose(profiles(g,prev),lane)
            else:
                with torch.no_grad():a=ACTIONS[int(model(model_input(buf)).argmax(1).item())]
            if a!='stay':canvas.press(KEYS[a],delay=180)
            if a=='left':lane=max(0,lane-1)
            elif a=='right':lane=min(2,lane+1)
            acts[a]+=1;steps+=1;prev=g;lat.append((time.time()-ts)*1000);time.sleep(.10)
    finally:
        duration=time.time()-t0;ctx.close();browser.close()
    return {'policy':policy,'duration_sec':round(duration,3),'death_detected':dead,'action_counts':dict(acts),'decisions':steps,'mean_decision_latency_ms':round(float(np.mean(lat)) if lat else 0,2)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--episodes',type=int,default=3);ap.add_argument('--seconds',type=int,default=38);args=ap.parse_args();root=Path(args.root)
    ck=torch.load(root/'stage10_imitation_policy.pt',map_location='cpu');m=Stage10Policy();m.load_state_dict(ck['model']);m.eval();rows=[]
    with sync_playwright() as p:
        for pol in ['stay','periodic_jump','corridor_cv','learned']:
            for i in range(args.episodes):
                try:r=episode(p,pol,m,args.seconds,i)
                except Exception as e:r={'policy':pol,'duration_sec':0,'death_detected':True,'error':str(e),'action_counts':{},'decisions':0}
                rows.append(r);print(json.dumps(r),flush=True)
    metrics={}
    for pol in ['stay','periodic_jump','corridor_cv','learned']:
        ds=[r['duration_sec'] for r in rows if r['policy']==pol];metrics[pol]={'episodes':len(ds),'median_survival_sec':round(float(statistics.median(ds)),3),'mean_survival_sec':round(float(np.mean(ds)),3),'max_survival_sec':round(float(max(ds)),3),'deaths':sum(bool(r.get('death_detected')) for r in rows if r['policy']==pol)}
    learned=metrics['learned']['median_survival_sec'];cheap=max(metrics[p]['median_survival_sec'] for p in ['stay','periodic_jump','corridor_cv']);maneuvers=set()
    for r in rows:
        if r['policy']=='learned':maneuvers|={a for a,n in r.get('action_counts',{}).items() if a!='stay' and n}
    accepted=learned>cheap and len(maneuvers)>=2
    out={'stage':'11-closed-loop-official-game-evaluation-v1','policy_contract':'pixel-policy-contract-v1.1','episodes_per_policy':args.episodes,'max_episode_seconds':args.seconds,'metrics':metrics,'learned_maneuvers_observed':sorted(maneuvers),'acceptance_gate':{'learned_median_survival_must_exceed_all_three_cheap_baselines':True,'minimum_distinct_learned_maneuvers':2},'privileged_game_state_used_by_learned_policy':False,'rows':rows,'accepted':accepted}
    (root/'stage11_summary.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2));raise SystemExit(0 if accepted else 21)
if __name__=='__main__':main()
