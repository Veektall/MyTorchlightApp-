#!/usr/bin/env python3
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np

import evaluate_stage15_pixel_evaluator_v17 as v17


def bootstrap_v18(canvas, tracker, tutorial_required, max_sec):
    t0=time.time();prev=None;motions=deque(maxlen=24);scores=deque(maxlen=120)
    last_score=None;last_change=-99.;last_score_submit=-99.;score_future=None
    prompt_future=None;last_prompt_submit=-99.;latched=None;latch_score=None;last_press=-99.;last_prompt_text=''
    last_prompt_confirmed=-99.;prompt_misses=0
    last_recover=-99.;last_safe_jump=-99.;events=[];seen=[];valid_reads=0;max_ever=0
    pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='stage15-pixel-v18')
    try:
        while time.time()-t0<max_sec:
            now=time.time()-t0
            png=canvas.screenshot();im=v17.s.pil_from_png(png);_,gray=v17.s.decode_png(png)
            if prev is not None:motions.append(v17.s.mean_abs(gray,prev))
            prev=gray

            if score_future is not None and score_future.done():
                try:v=score_future.result()
                except Exception:v=None
                score_future=None
                if v is not None:
                    valid_reads+=1
                    if last_score is None or (v<=15 and last_score>=35 and now-last_recover<5.0):
                        last_score=v;last_change=now
                        events.append({'t':round(now,2),'event':'score_reset','score':v})
                    elif v>=last_score and v<=last_score+250:
                        if v>last_score:last_change=now
                        last_score=v
                    max_ever=max(max_ever,int(last_score or 0));scores.append((now,int(last_score or 0)))
            if score_future is None and now-last_score_submit>=.7:
                score_future=pool.submit(v17.score_job,im.copy());last_score_submit=now

            if prompt_future is not None and prompt_future.done():
                try:d,txt=prompt_future.result()
                except Exception:d,txt=None,''
                prompt_future=None;last_prompt_text=txt
                if d:
                    prompt_misses=0;last_prompt_confirmed=now
                    if d!=latched:
                        latched=d;latch_score=last_score
                        if not seen or seen[-1]!=d:seen.append(d)
                        events.append({'t':round(now,2),'event':'prompt_latched','direction':d,'score':last_score,'text':txt[-120:]})
                else:
                    prompt_misses+=1
            stalled=(last_score is not None and now-last_change>=1.6)
            if prompt_future is None and now-last_prompt_submit>=.9 and (tutorial_required or stalled or latched is not None):
                prompt_future=pool.submit(v17.prompt_job,im.copy());last_prompt_submit=now

            if latched:
                progressed=(latch_score is not None and last_score is not None and last_score>=latch_score+2)
                prompt_absent=(prompt_misses>=2 and now-last_prompt_confirmed>=2.4)
                collision_absent=(prompt_misses>=3 and now-last_prompt_confirmed>=5.5 and stalled)
                if progressed and prompt_absent:
                    events.append({'t':round(now,2),'event':'prompt_cleared_by_absence_and_progress','direction':latched,'from':latch_score,'to':last_score})
                    latched=None;latch_score=None;prompt_misses=0
                elif collision_absent:
                    # Correct action may have cleared the prompt immediately before a collision. Drop the stale
                    # direction so the pixel-stall recovery path can restart while preserving tutorial progress.
                    events.append({'t':round(now,2),'event':'stale_prompt_released_for_recovery','direction':latched,'score':last_score})
                    latched=None;latch_score=None;prompt_misses=0
                elif now-last_press>=.42:
                    canvas.press(v17.PROMPT_KEY[latched],delay=180);last_press=now
                    events.append({'t':round(now,2),'event':'prompt_press','direction':latched,'score':last_score})
            else:
                if last_score is not None and now-last_change<1.8 and now-last_safe_jump>=.95:
                    canvas.press('ArrowUp',delay=180);last_safe_jump=now
                if (last_score is None or now-last_change>=6.0) and now-last_recover>=1.8:
                    key=['Enter','Space','ArrowUp'][int(now/1.8)%3]
                    canvas.press(key,delay=180);last_recover=now
                    events.append({'t':round(now,2),'event':'recovery_press','key':key,'score':last_score})

            if last_score is not None and len(scores)>=5:
                med=float(np.median(motions)) if motions else 0.0
                recent=[(t,v) for t,v in scores if now-t<=9.0]
                growth=(last_score-min(v for _,v in recent)) if len(recent)>=4 else 0
                advancing=now-last_change<1.5
                threshold=220 if tutorial_required else 18
                if max_ever>=threshold and growth>=12 and advancing and med>.0025 and latched is None:
                    v17.v15.v13.v12.v11.v10.v9.arm_tracker(tracker,last_score)
                    return {'ok':True,'tutorial_completed':bool(tutorial_required),'startup_controller':'persistent_latched_prompt_v18',
                            'tutorial_prompt_sequence':seen,'tutorial_events':events[-300:],'score_at_handoff':int(last_score),
                            'max_bootstrap_score':int(max_ever),'recent_score_growth':int(growth),'motion_median':round(med,6),
                            'valid_score_reads':valid_reads,'policy_clock_reset_after_tutorial':True,'score_hud_xy':[.9275,.0675]}
            time.sleep(.035)
    finally:
        pool.shutdown(wait=False,cancel_futures=True)
    return {'ok':False,'reason':'persistent_latched_bootstrap_timeout_v18','startup_controller':'persistent_latched_prompt_v18',
            'tutorial_prompt_sequence':seen,'tutorial_events':events[-380:],'last_prompt_text':last_prompt_text,
            'latched_prompt':latched,'prompt_misses':prompt_misses,'last_score':last_score,'max_bootstrap_score':max_ever,
            'valid_score_reads':valid_reads,'motion_median':round(float(np.median(motions)),6) if motions else 0.0}

v17.bootstrap=bootstrap_v18

if __name__=='__main__':
    v17.main()
