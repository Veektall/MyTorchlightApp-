#!/usr/bin/env python3
import argparse, json, os, re, shutil, subprocess, time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import torch

import evaluate_stage15_pixel_evaluator_v15 as v15

s = v15.s
ACTIONS = s.ACTIONS
KEYS = s.KEYS
PROMPT_KEY = {'up':'ArrowUp','down':'ArrowDown','left':'ArrowLeft','right':'ArrowRight','space':'Space'}


def prompt_job(im):
    """Pixel-only tutorial prompt reader. It is never policy input and runs off-thread."""
    from PIL import ImageOps, ImageEnhance, Image
    w,h=im.size
    roi=im.crop((int(w*.24), int(h*.36), int(w*.78), int(h*.68)))
    g=ImageOps.grayscale(roi).resize((roi.width*2, roi.height*2), Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(2.6)
    try:
        text=s.pytesseract.image_to_string(g, config='--psm 11', lang='eng').lower()
    except Exception:
        return None,''
    n=' '.join(re.sub(r'[^a-z]+',' ',text).split())
    # Reject background words such as "up" unless the rendered instruction itself is present.
    instruction = ('press' in n or 'arrow' in n or 'key' in n or 'swipe' in n)
    d=None
    if instruction:
        if 'left' in n: d='left'
        elif 'right' in n: d='right'
        elif 'down' in n or 'roll' in n: d='down'
        elif 'up' in n or 'jump' in n: d='up'
        elif 'space' in n or 'hoverboard' in n: d='space'
    return d,text[-260:]


def score_job(im):
    try:
        c=s.digit_candidates(im)
        return int(c[0]['value']) if c else None
    except Exception:
        return None


def death_text_job(im):
    try:return s.ocr_text(im)
    except Exception:return ''


def start_recording(path):
    display=os.getenv('DISPLAY')
    if not display:return None
    return subprocess.Popen([
        'ffmpeg','-y','-loglevel','warning','-f','x11grab','-draw_mouse','0','-framerate','30',
        '-video_size','1280x720','-i',f'{display}+0,0','-an','-c:v','libvpx-vp9',
        '-deadline','realtime','-cpu-used','8','-b:v','1600k',str(path)
    ],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def stop_recording(p):
    if not p or p.poll() is not None:return
    try:p.stdin.write(b'q\n');p.stdin.flush();p.wait(timeout=6)
    except Exception:
        try:p.terminate();p.wait(timeout=3)
        except Exception:
            try:p.kill()
            except Exception:pass


def bootstrap(canvas, tracker, tutorial_required, max_sec):
    """Complete tutorial/restart from rendered pixels only, once per persistent browser session."""
    t0=time.time();prev=None;motions=deque(maxlen=24);scores=deque(maxlen=120)
    last_score=None;last_change=-99.;last_score_submit=-99.;score_future=None
    prompt_future=None;last_prompt_submit=-99.;latched=None;latch_score=None;last_press=-99.;last_prompt_text=''
    last_recover=-99.;last_safe_jump=-99.;events=[];seen=[];valid_reads=0;max_ever=0
    pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='stage15-pixel')
    try:
        while time.time()-t0<max_sec:
            now=time.time()-t0
            png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
            if prev is not None:motions.append(s.mean_abs(gray,prev))
            prev=gray

            if score_future is not None and score_future.done():
                try:v=score_future.result()
                except Exception:v=None
                score_future=None
                if v is not None:
                    valid_reads+=1
                    # Explicit restart keys may legitimately reset score to zero.
                    if last_score is None or (v<=15 and last_score>=35 and now-last_recover<5.0):
                        last_score=v;last_change=now
                        events.append({'t':round(now,2),'event':'score_reset','score':v})
                    elif v>=last_score and v<=last_score+250:
                        if v>last_score:last_change=now
                        last_score=v
                    max_ever=max(max_ever,int(last_score or 0));scores.append((now,int(last_score or 0)))
            if score_future is None and now-last_score_submit>=.7:
                score_future=pool.submit(score_job,im.copy());last_score_submit=now

            if prompt_future is not None and prompt_future.done():
                try:d,txt=prompt_future.result()
                except Exception:d,txt=None,''
                prompt_future=None;last_prompt_text=txt
                if d:
                    if d!=latched:
                        latched=d;latch_score=last_score
                        if not seen or seen[-1]!=d:seen.append(d)
                        events.append({'t':round(now,2),'event':'prompt_latched','direction':d,'score':last_score,'text':txt[-120:]})
            # OCR only when tutorial is plausible or score has stalled; never in the learned-policy loop.
            stalled=(last_score is not None and now-last_change>=1.6)
            if prompt_future is None and now-last_prompt_submit>=1.0 and (tutorial_required or stalled):
                prompt_future=pool.submit(prompt_job,im.copy());last_prompt_submit=now

            # A recognized prompt remains authoritative across OCR misses. Release only on causal score progress
            # or on recognition of a different rendered instruction.
            if latched:
                if latch_score is not None and last_score is not None and last_score>=latch_score+9:
                    events.append({'t':round(now,2),'event':'prompt_cleared_by_score','direction':latched,'from':latch_score,'to':last_score})
                    latched=None;latch_score=None
                elif now-last_press>=.42:
                    canvas.press(PROMPT_KEY[latched],delay=180);last_press=now
                    events.append({'t':round(now,2),'event':'prompt_press','direction':latched,'score':last_score})
            else:
                # Between tutorial checkpoints, keep the runner alive without using game internals.
                if last_score is not None and now-last_change<1.8 and now-last_safe_jump>=.95:
                    canvas.press('ArrowUp',delay=180);last_safe_jump=now
                # On a long pixel-score stall with no recognized prompt, recover from collision/death and keep
                # tutorial progress in this same browser context.
                if (last_score is None or now-last_change>=6.5) and now-last_recover>=2.1:
                    key=['Enter','Space','ArrowUp'][int(now/2.1)%3]
                    canvas.press(key,delay=180);last_recover=now
                    events.append({'t':round(now,2),'event':'recovery_press','key':key,'score':last_score})

            if last_score is not None and len(scores)>=5:
                med=float(np.median(motions)) if motions else 0.0
                recent=[(t,v) for t,v in scores if now-t<=9.0]
                growth=(last_score-min(v for _,v in recent)) if len(recent)>=4 else 0
                advancing=now-last_change<1.5
                # Initial session must get beyond the known tutorial-score region. Subsequent restarts need only
                # prove a fresh, advancing endless run because tutorial state is retained by the context.
                threshold=220 if tutorial_required else 18
                evidence=(max_ever>=threshold and growth>=12 and advancing and med>.0025 and latched is None)
                if evidence:
                    v15.v13.v12.v11.v10.v9.arm_tracker(tracker,last_score)
                    return {'ok':True,'tutorial_completed':bool(tutorial_required),'startup_controller':'persistent_latched_prompt_v17',
                            'tutorial_prompt_sequence':seen,'tutorial_events':events[-260:],'score_at_handoff':int(last_score),
                            'max_bootstrap_score':int(max_ever),'recent_score_growth':int(growth),'motion_median':round(med,6),
                            'valid_score_reads':valid_reads,'policy_clock_reset_after_tutorial':True,'score_hud_xy':[.9275,.0675]}
            time.sleep(.035)
    finally:
        pool.shutdown(wait=False,cancel_futures=True)
    return {'ok':False,'reason':'persistent_latched_bootstrap_timeout','startup_controller':'persistent_latched_prompt_v17',
            'tutorial_prompt_sequence':seen,'tutorial_events':events[-340:],'last_prompt_text':last_prompt_text,
            'latched_prompt':latched,'last_score':last_score,'max_bootstrap_score':max_ever,'valid_score_reads':valid_reads,
            'motion_median':round(float(np.median(motions)),6) if motions else 0.0}


def run_policy_episode(canvas,policy,ep,checkpoint,out,watchdog,tracker):
    learned=s.LearnedPolicy(checkpoint) if policy=='learned' else None
    corr=s.CorridorPolicy() if policy=='corridor_cv' else None
    ring=deque(maxlen=8);prev=None;motion=deque(maxlen=12);actions=[];confs=[];last_dec=-99.;last_jump=-99.
    max_score=int(tracker.last_score or 0);last_score=max_score;last_score_t=0.0;score_reads=[]
    score_future=None;last_score_submit=-99.;death_future=None;last_death_submit=-99.;death_text=''
    pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='stage15-eval')
    t0=time.time();dead=False;death_reason=None
    rec_path=out/f'{policy}_ep{ep}.webm';rec=start_recording(rec_path)
    try:
        while True:
            t=time.time()-t0
            if t>watchdog: break
            png=canvas.screenshot();im=s.pil_from_png(png);rgb,gray=s.decode_png(png)
            old_prev=prev
            if old_prev is not None:motion.append(s.mean_abs(gray,old_prev))
            prev=gray;ring.append(rgb)

            if score_future is not None and score_future.done():
                try:v=score_future.result()
                except Exception:v=None
                score_future=None
                if v is not None and v>=last_score and v<=last_score+350:
                    if v>last_score:last_score_t=t
                    last_score=v;max_score=max(max_score,v);score_reads.append([round(t,2),int(v)])
            if score_future is None and t-last_score_submit>=.85:
                score_future=pool.submit(score_job,im.copy());last_score_submit=t

            stalled=t-last_score_t>4.5
            lowmotion=(len(motion)>=7 and float(np.median(motion))<.0030)
            color=s.legacy_death(rgb)
            if stalled and death_future is None and t-last_death_submit>=2.0:
                death_future=pool.submit(death_text_job,im.copy());last_death_submit=t
            if death_future is not None and death_future.done():
                try:death_text=death_future.result() or ''
                except Exception:death_text=''
                death_future=None
            kw=next((w for w in s.DEATH_WORDS if w in death_text),None)
            if (kw and stalled) or (color and stalled) or (stalled and lowmotion and t>8):
                dead=True;death_reason=('text:'+kw) if kw else ('legacy_color+score_stall' if color else 'score_stall+pixel_freeze');break

            if t-last_dec>=.24:
                a='stay';c=1.0
                if policy=='always_jump':
                    a='jump' if t-last_jump>=.82 else 'stay'
                    if a=='jump':last_jump=t
                elif policy=='corridor_cv' and old_prev is not None:a,c=corr.act(gray,old_prev,t)
                elif policy=='learned':a,c=learned.act(ring,t)
                elif policy!='stay':raise ValueError(policy)
                if a!='stay':canvas.press(KEYS[a],delay=180)
                actions.append(a);confs.append(c);last_dec=t
            time.sleep(.035)
    finally:
        stop_recording(rec);pool.shutdown(wait=False,cancel_futures=True)
    try:(out/f'{policy}_ep{ep}_final.png').write_bytes(canvas.screenshot())
    except Exception:pass
    cnt=Counter(actions);dur=time.time()-t0
    return {'policy':policy,'episode':ep,'valid':bool(dead and max_score>0),'death_detected':dead,
            'death_reason':death_reason,'reason':None if dead else 'watchdog_abort_before_verified_death',
            'survival_sec':round(dur,3),'max_pixel_score':int(max_score),'score_reads':score_reads[-40:],
            'action_counts':{a:cnt[a] for a in ACTIONS},'mean_confidence':round(float(np.mean(confs)),4) if confs else None,
            'score_metric_available':bool(max_score>0),'score_source':'rendered_canvas_pixels_ocr_monotonic_track',
            'policy_input':'pixels_only_8_rgb_frames' if policy=='learned' else 'pixels_or_time_baseline','video_file':rec_path.name}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--learned-episodes',type=int,default=3);ap.add_argument('--watchdog-seconds',type=float,default=180)
    args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True);results=[]
    with s.sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=s.BROWSER_ARGS)
        context=page=canvas=None;session_video=None
        try:
            # One persistent context: tutorial state is environment setup and must not reset between benchmark episodes.
            context,page,canvas=s.open_game(browser,out/'session_video');session_video=page.video
            plan=[('stay',1),('always_jump',1),('corridor_cv',1)]+[('learned',i) for i in range(1,args.learned_episodes+1)]
            tutorial_required=True
            for pol,ep in plan:
                tracker=s.ScoreTracker();start=bootstrap(canvas,tracker,tutorial_required,600 if tutorial_required else 75)
                if not start.get('ok'):
                    r={'policy':pol,'episode':ep,'valid':False,'startup':start,'reason':'startup_or_restart_failed'}
                else:
                    tutorial_required=False
                    r=run_policy_episode(canvas,pol,ep,args.checkpoint,out,args.watchdog_seconds,tracker);r['startup']=start
                results.append(r);print(json.dumps(r),flush=True)
                if pol=='stay' and not r.get('valid'):
                    print('Evaluator calibration failed on stay; refusing competence benchmark.',flush=True);break
        finally:
            if context is not None:
                try:context.close()
                except Exception:pass
            if session_video is not None:
                try:shutil.copy2(Path(session_video.path()),out/'stage15_session.webm')
                except Exception:pass
            try:browser.close()
            except Exception:pass

    by={p:[r for r in results if r.get('policy')==p and r.get('valid')] for p in ['stay','always_jump','corridor_cv','learned']}
    agg={}
    for pol,rr in by.items():
        scores=[r['max_pixel_score'] for r in rr];surv=[r['survival_sec'] for r in rr]
        agg[pol]={'valid_episodes':len(rr),'mean_score':round(float(np.mean(scores)),1) if scores else None,
                  'median_score':round(float(np.median(scores)),1) if scores else None,'max_score':max(scores) if scores else None,
                  'mean_survival_sec':round(float(np.mean(surv)),3) if surv else None,'deaths':sum(r.get('death_detected',False) for r in rr)}
    eval_ok=bool(len(by['stay'])==1 and len(by['learned'])==args.learned_episodes and all(r.get('score_metric_available') and r.get('death_detected') for r in by['stay']+by['learned']))
    cheap=[agg['stay']['median_score'],agg['always_jump']['median_score']];lm=agg['learned']['median_score']
    beats=bool(eval_ok and lm is not None and all(x is not None and lm>x for x in cheap))
    best=max(by['learned'],key=lambda r:r['max_pixel_score']) if by['learned'] else None
    summary={'stage':'15-pixel-evaluator-repair-v17','policy_contract':'pixel-policy-contract-v1.1','official_game':'https://poki.com/en/g/subway-surfers',
             'persistent_context_tutorial_once':True,'watchdog_is_safety_abort_not_benchmark_horizon_sec':args.watchdog_seconds,
             'results':results,'aggregate':agg,'normal_endless_play_verified':eval_ok,'pixel_score_metric_available':bool(best),
             'run_to_verified_death':eval_ok,'evaluator_discriminative':eval_ok,'benchmark_complete':eval_ok,
             'learned_beats_both_cheap_baselines':beats,
             'competence_claim':bool(beats and (agg['corridor_cv']['median_score'] is None or lm>=.8*agg['corridor_cv']['median_score'])),
             'highest_learned_score':best['max_pixel_score'] if best else None,'highest_score_video':best.get('video_file') if best else None,
             'geometry_comparison_started':False,'completed':eval_ok}
    (out/'stage15_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2),flush=True)
    raise SystemExit(0 if eval_ok else 61)

if __name__=='__main__':main()
