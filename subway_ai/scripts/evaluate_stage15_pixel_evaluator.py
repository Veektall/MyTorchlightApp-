#!/usr/bin/env python3
import argparse, io, json, os, re, time, shutil
from collections import Counter, deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageEnhance
import pytesseract
import torch
from playwright.sync_api import sync_playwright

from stage10_v4_model import ACTIONS, Stage10Policy
from evaluate_stage11_closed_loop import CorridorPolicy, KEYS, BROWSER_ARGS, focus_canvas, decode_png, mean_abs, is_death as legacy_death
from live_runtime_v2 import robust_open_game as base_open_game

W,H=96,54
DEATH_WORDS=('revive','game over','continue','run again','watch','save me','try again','play again')


def pil_from_png(png): return Image.open(io.BytesIO(png)).convert('RGB')

def ocr_text(im):
    g=ImageOps.grayscale(im);g=ImageEnhance.Contrast(g).enhance(2.2);g=g.resize((g.width*2,g.height*2),Image.Resampling.BICUBIC)
    try:return pytesseract.image_to_string(g,config='--psm 11',lang='eng').lower()
    except Exception:return ''

def digit_candidates(im):
    # Pixel-only HUD read. Search upper half and keep stable numeric tracks by screen position.
    crop=im.crop((0,0,im.width,int(im.height*.55)))
    variants=[]
    g=ImageOps.grayscale(crop).resize((crop.width*3,crop.height*3),Image.Resampling.BICUBIC)
    variants.append(ImageEnhance.Contrast(g).enhance(2.6))
    variants.append(g.point(lambda p:255 if p>175 else 0))
    out=[]
    for v in variants:
        try:d=pytesseract.image_to_data(v,config='--psm 11 -c tessedit_char_whitelist=0123456789',output_type=pytesseract.Output.DICT)
        except Exception:continue
        n=len(d.get('text',[]))
        for i in range(n):
            s=re.sub(r'\D','',d['text'][i] or '')
            if not s:continue
            try:conf=float(d['conf'][i])
            except Exception:conf=-1
            if conf<18:continue
            val=int(s)
            if val<0 or val>999999999:continue
            x=(d['left'][i]+d['width'][i]/2)/v.width;y=(d['top'][i]+d['height'][i]/2)/v.height
            w=d['width'][i]/v.width;h=d['height'][i]/v.height
            out.append({'value':val,'x':x,'y':y,'w':w,'h':h,'conf':conf})
    # de-dupe near-identical candidates from preprocessing variants
    ded=[]
    for c in sorted(out,key=lambda z:z['conf'],reverse=True):
        if any(abs(c['x']-q['x'])<.018 and abs(c['y']-q['y'])<.018 and c['value']==q['value'] for q in ded):continue
        ded.append(c)
    return ded

class ScoreTracker:
    def __init__(self): self.tracks=[];self.locked=None;self.last_score=None;self.last_score_t=None
    def update_search(self,cands,t):
        used=set()
        for c in cands:
            best=None;bd=.09
            for j,tr in enumerate(self.tracks):
                if j in used:continue
                d=((c['x']-tr['x'])**2+(c['y']-tr['y'])**2)**.5
                if d<bd:best=j;bd=d
            if best is None:
                self.tracks.append({'x':c['x'],'y':c['y'],'w':c['w'],'h':c['h'],'vals':[(t,c['value'])],'conf':[c['conf']]});used.add(len(self.tracks)-1)
            else:
                tr=self.tracks[best];a=.25;tr['x']=(1-a)*tr['x']+a*c['x'];tr['y']=(1-a)*tr['y']+a*c['y'];tr['w']=max(tr['w'],c['w']);tr['h']=max(tr['h'],c['h']);tr['vals'].append((t,c['value']));tr['conf'].append(c['conf']);used.add(best)
    def choose_lock(self):
        cand=[]
        for i,tr in enumerate(self.tracks):
            vals=[v for _,v in tr['vals']]
            if len(vals)<3:continue
            nondec=sum(vals[k]>=vals[k-1] for k in range(1,len(vals)))/max(1,len(vals)-1)
            growth=max(vals)-min(vals)
            if nondec<.65 or growth<10:continue
            score=(growth*2+max(vals)+len(vals)*5+np.mean(tr['conf']))
            cand.append((score,i))
        if not cand:return False
        self.locked=self.tracks[max(cand)[1]]
        vals=[v for _,v in self.locked['vals']];self.last_score=max(vals);self.last_score_t=self.locked['vals'][-1][0];return True
    def read_locked(self,im,t):
        if self.locked is None:return None
        cands=digit_candidates(im);x0=self.locked['x'];y0=self.locked['y'];near=[]
        for c in cands:
            d=((c['x']-x0)**2+(c['y']-y0)**2)**.5
            if d<.12:near.append((d,c))
        if not near:return None
        # prefer plausible non-decreasing score candidate nearest locked HUD location
        near.sort(key=lambda z:(z[0],-z[1]['conf']))
        vals=[c for _,c in near]
        plausible=[c for c in vals if self.last_score is None or (c['value']>=max(0,self.last_score-3) and c['value']<=self.last_score+250000)]
        c=(plausible or vals)[0];v=c['value']
        if self.last_score is None or v>=self.last_score:
            if self.last_score is None or v>self.last_score:self.last_score_t=t
            self.last_score=v;self.locked['x']=.8*self.locked['x']+.2*c['x'];self.locked['y']=.8*self.locked['y']+.2*c['y']
        return self.last_score

class LearnedPolicy:
    def __init__(self,checkpoint):
        self.model=Stage10Policy();ck=torch.load(checkpoint,map_location='cpu');self.model.load_state_dict(ck['model']);self.model.eval();self.last={}
    def act(self,ring,t):
        if len(ring)<8:return 'stay',1.0
        x=np.stack(ring).astype(np.float32)/255.0;x=torch.from_numpy(x).permute(0,3,1,2).unsqueeze(0)
        with torch.no_grad():pr=self.model(x).softmax(1)[0]
        order=torch.argsort(pr,descending=True).tolist();cool={'left':.45,'right':.45,'jump':.58,'roll':.68,'stay':0.0};chosen='stay'
        for i in order:
            a=ACTIONS[i]
            if t-self.last.get(a,-99)>=cool[a]:chosen=a;break
        self.last[chosen]=t;return chosen,float(pr[ACTIONS.index(chosen)])

def open_game(browser,video_dir):
    # Reuse the proven robust opener, but wrap a fresh recording context by reproducing its navigation contract.
    context=browser.new_context(viewport={'width':1280,'height':720},locale='en-US',record_video_dir=str(video_dir),record_video_size={'width':1280,'height':720})
    page=context.new_page();page.goto('https://poki.com/en/g/subway-surfers',wait_until='domcontentloaded',timeout=120000)
    deadline=time.time()+100;canvas=None
    while time.time()<deadline:
        fs=[f for f in page.frames if '.gdn.poki.com' in f.url]
        if fs:
            c=fs[-1].locator('#pixi-canvas')
            if c.count():canvas=c;break
        time.sleep(.6)
    if canvas is None:context.close();raise RuntimeError('official Pixi canvas not found')
    focus_canvas(canvas);return context,page,canvas

def startup_and_lock_score(canvas,tracker,max_sec=24):
    keys=['Space','Enter','ArrowUp','Space','ArrowLeft','ArrowRight','ArrowUp','Space']
    prev=None;motions=deque(maxlen=8);t0=time.time();last_key=-99;search_reads=0
    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=pil_from_png(png);rgb,gray=decode_png(png)
        if prev is not None:motions.append(mean_abs(gray,prev))
        prev=gray
        if now-last_key>1.4:
            focus_canvas(canvas);canvas.press(keys[int(now/1.4)%len(keys)],delay=120);last_key=now
        if search_reads<18:
            tracker.update_search(digit_candidates(im),now);search_reads+=1
            if tracker.choose_lock():
                # prove gameplay, not just menu: locked numeric HUD must continue increasing while scene moves.
                s0=tracker.last_score;proof_t=time.time();proof_motion=[]
                while time.time()-proof_t<4.5:
                    png2=canvas.screenshot();im2=pil_from_png(png2);_,g2=decode_png(png2);proof_motion.append(mean_abs(g2,prev));prev=g2;tracker.read_locked(im2,time.time()-t0);time.sleep(.35)
                if tracker.last_score is not None and s0 is not None and tracker.last_score>=s0+5 and np.median(proof_motion)>.0025:
                    return {'ok':True,'score_start':s0,'score_after_proof':tracker.last_score,'proof_motion_median':round(float(np.median(proof_motion)),6),'score_hud_xy':[round(tracker.locked['x'],4),round(tracker.locked['y'],4)]}
        time.sleep(.28)
    return {'ok':False,'reason':'no_verified_endless_play_or_pixel_score_lock','tracks':len(tracker.tracks),'motion_median':round(float(np.median(motions)),6) if motions else 0.0}

def run_episode(browser,policy,ep,checkpoint,outdir,watchdog):
    vdir=outdir/'raw_video';vdir.mkdir(parents=True,exist_ok=True);context=page=canvas=None;video=None
    result={'policy':policy,'episode':ep,'valid':False}
    try:
        context,page,canvas=open_game(browser,vdir);video=page.video
        tracker=ScoreTracker();start=startup_and_lock_score(canvas,tracker)
        result['startup']=start
        if not start.get('ok'):result['reason']='startup_or_score_lock_failed';return result
        learned=LearnedPolicy(checkpoint) if policy=='learned' else None;corr=CorridorPolicy() if policy=='corridor_cv' else None
        ring=deque(maxlen=8);prev=None;motion=deque(maxlen=10);actions=[];confs=[];last_dec=-99.;last_jump=-99.;last_ocr=-99.;last_text=-99.;dead=False;death_reason=None;t0=time.time();max_score=tracker.last_score or 0;score_reads=[]
        while True:
            t=time.time()-t0
            if t>watchdog:
                result['reason']='watchdog_abort_before_verified_death';break
            png=canvas.screenshot();im=pil_from_png(png);rgb,gray=decode_png(png)
            if prev is not None:motion.append(mean_abs(gray,prev))
            prev=gray;ring.append(rgb)
            if t-last_ocr>.65:
                s=tracker.read_locked(im,t);last_ocr=t
                if s is not None:max_score=max(max_score,s);score_reads.append([round(t,2),int(s)])
            text=''
            if t-last_text>1.4:
                text=ocr_text(im);last_text=t
            stalled=(tracker.last_score_t is not None and t-tracker.last_score_t>2.0)
            lowmotion=(len(motion)>=6 and float(np.median(motion))<.0022)
            kw=next((w for w in DEATH_WORDS if w in text),None)
            color=legacy_death(rgb)
            if (kw and stalled) or (color and stalled and lowmotion) or (stalled and lowmotion and t>5 and len(text.strip())>8):
                dead=True;death_reason=('text:'+kw) if kw else ('legacy_color+freeze' if color else 'score_stall+freeze+overlay');break
            if t-last_dec>=.26:
                a='stay';c=1.0
                if policy=='stay':a='stay'
                elif policy=='always_jump':
                    a='jump' if t-last_jump>=.82 else 'stay'
                    if a=='jump':last_jump=t
                elif policy=='corridor_cv':a,c=corr.act(gray,prev,t)
                elif policy=='learned':a,c=learned.act(ring,t)
                else:raise ValueError(policy)
                if a!='stay':canvas.press(KEYS[a],delay=160)
                actions.append(a);confs.append(c);last_dec=t
            time.sleep(.045)
        dur=time.time()-t0;cnt=Counter(actions);result.update({'valid':bool(dead and max_score>0),'death_detected':dead,'death_reason':death_reason,'survival_sec':round(dur,3),'max_pixel_score':int(max_score),'score_reads':score_reads[-30:],'action_counts':{a:cnt[a] for a in ACTIONS},'mean_confidence':round(float(np.mean(confs)),4) if confs else None,'score_metric_available':bool(max_score>0),'score_source':'rendered_canvas_pixels_ocr_monotonic_track','policy_input':'pixels_only_8_rgb_frames' if policy=='learned' else 'pixels_or_time_baseline'})
        # final evidence frame
        try:(outdir/f'{policy}_ep{ep}_final.png').write_bytes(canvas.screenshot())
        except Exception:pass
        return result
    finally:
        if context is not None:
            try:context.close()
            except Exception:pass
        if video is not None:
            try:
                p=Path(video.path());dest=outdir/f'{policy}_ep{ep}.webm';shutil.copy2(p,dest);result['video_file']=dest.name
            except Exception as e:result['video_error']=str(e)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True);ap.add_argument('--learned-episodes',type=int,default=3);ap.add_argument('--watchdog-seconds',type=float,default=180);args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=BROWSER_ARGS)
        try:
            plan=[('stay',1),('always_jump',1),('corridor_cv',1)]+[('learned',i) for i in range(1,args.learned_episodes+1)]
            for pol,ep in plan:
                try:r=run_episode(browser,pol,ep,args.checkpoint,out,args.watchdog_seconds)
                except Exception as e:r={'policy':pol,'episode':ep,'valid':False,'reason':str(e)}
                results.append(r);print(json.dumps(r),flush=True)
                if pol=='stay' and not r.get('valid'):
                    print('Evaluator calibration failed on stay; refusing competence benchmark.',flush=True);break
        finally:browser.close()
    by={p:[r for r in results if r.get('policy')==p and r.get('valid')] for p in ['stay','always_jump','corridor_cv','learned']}
    agg={}
    for p,rr in by.items():
        scores=[r['max_pixel_score'] for r in rr];surv=[r['survival_sec'] for r in rr]
        agg[p]={'valid_episodes':len(rr),'mean_score':round(float(np.mean(scores)),1) if scores else None,'median_score':round(float(np.median(scores)),1) if scores else None,'max_score':max(scores) if scores else None,'mean_survival_sec':round(float(np.mean(surv)),3) if surv else None,'deaths':sum(r.get('death_detected',False) for r in rr)}
    eval_ok=bool(len(by['stay'])==1 and len(by['learned'])==args.learned_episodes and all(r.get('score_metric_available') and r.get('death_detected') for r in by['stay']+by['learned']))
    cheap=[agg['stay']['median_score'],agg['always_jump']['median_score']];lm=agg['learned']['median_score'];beats=bool(eval_ok and lm is not None and all(x is not None and lm>x for x in cheap))
    best=max(by['learned'],key=lambda r:r['max_pixel_score']) if by['learned'] else None
    summary={'stage':'15-pixel-evaluator-repair-v1','policy_contract':'pixel-policy-contract-v1.1','official_game':'https://poki.com/en/g/subway-surfers','watchdog_is_safety_abort_not_benchmark_horizon_sec':args.watchdog_seconds,'results':results,'aggregate':agg,'normal_endless_play_verified':eval_ok,'pixel_score_metric_available':bool(best),'run_to_verified_death':eval_ok,'evaluator_discriminative':eval_ok,'benchmark_complete':eval_ok,'learned_beats_both_cheap_baselines':beats,'competence_claim':bool(beats and (agg['corridor_cv']['median_score'] is None or lm>=.8*agg['corridor_cv']['median_score'])),'highest_learned_score':best['max_pixel_score'] if best else None,'highest_score_video':best.get('video_file') if best else None,'geometry_comparison_started':False,'completed':eval_ok}
    (out/'stage15_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2),flush=True)
    raise SystemExit(0 if eval_ok else 61)
if __name__=='__main__':main()
