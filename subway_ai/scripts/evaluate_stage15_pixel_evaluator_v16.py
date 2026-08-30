#!/usr/bin/env python3
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import ImageOps, ImageEnhance, Image
import pytesseract

import evaluate_stage15_pixel_evaluator_v15 as v15

s = v15.s
PROMPT_KEY = {'up':'ArrowUp','down':'ArrowDown','left':'ArrowLeft','right':'ArrowRight'}


def _prompt_ocr_job(im):
    """OCR only the fixed tutorial prompt ROI; runs off the control thread."""
    w,h=im.size
    roi=im.crop((int(w*.33), int(h*.43), int(w*.68), int(h*.58)))
    g=ImageOps.grayscale(roi).resize((roi.width*4, roi.height*4), Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(3.0)
    variants=(g, g.point(lambda p:255 if p>155 else 0))
    texts=[]
    for x in variants:
        try:
            texts.append(pytesseract.image_to_string(x, config='--psm 6', lang='eng').lower())
        except Exception:
            pass
    text=' '.join(texts)
    n=' '.join(re.sub(r'[^a-z]+',' ',text).split())
    direction=None
    if 'left' in n: direction='left'
    elif 'right' in n: direction='right'
    elif 'down' in n or 'roll' in n: direction='down'
    elif 'up' in n or 'jump' in n: direction='up'
    return direction, text[-300:]


def startup_async_prompt_directed(canvas, tracker, max_sec=240):
    t0=time.time(); prev=None; motions=deque(maxlen=30); scores=deque(maxlen=240)
    last_score=None; last_change=-99.; last_score_read=-99.; last_press=-99.; last_boot=-99.
    current_prompt=None; last_prompt_seen=-99.; last_ocr_submit=-99.; pending=None
    events=[]; valid_reads=0; seen=[]; last_text=''; no_prompt_since=None
    pool=ThreadPoolExecutor(max_workers=1, thread_name_prefix='tutorial-ocr')
    try:
        while time.time()-t0 < max_sec:
            now=time.time()-t0
            png=canvas.screenshot(); im=s.pil_from_png(png); _,gray=s.decode_png(png)
            if prev is not None: motions.append(s.mean_abs(gray,prev))
            prev=gray

            # Tight six-digit score ROI: enough to prove progression without game internals.
            if now-last_score_read >= .35:
                c=s.digit_candidates(im); last_score_read=now
                if c:
                    v=int(c[0]['value']); valid_reads+=1
                    if last_score is None:
                        last_score=v; last_change=now
                    elif v>=last_score and v<=last_score+120:
                        if v>last_score: last_change=now
                        last_score=v
                    scores.append((now,int(last_score)))

            # Consume completed OCR without blocking gameplay control.
            if pending is not None and pending.done():
                try:d,txt=pending.result()
                except Exception:d,txt=None,''
                pending=None; last_text=txt
                if d:
                    if current_prompt != d:
                        current_prompt=d
                        if not seen or seen[-1]!=d: seen.append(d)
                        events.append({'t':round(now,2),'event':'prompt_seen','direction':d,'score':last_score,'text':txt[-120:]})
                    last_prompt_seen=now; no_prompt_since=None
                elif now-last_prompt_seen > 1.8:
                    if current_prompt is not None:
                        events.append({'t':round(now,2),'event':'prompt_clear_candidate','previous':current_prompt,'score':last_score})
                    current_prompt=None
                    if no_prompt_since is None:no_prompt_since=now

            if pending is None and now-last_ocr_submit >= .45:
                # PIL crop is copied before the worker receives it.
                pending=pool.submit(_prompt_ocr_job, im.copy()); last_ocr_submit=now

            if current_prompt:
                # Repeated trusted key while the rendered prompt remains the same.
                if now-last_press >= .34:
                    key=PROMPT_KEY[current_prompt]
                    canvas.press(key,delay=180); last_press=now
                    events.append({'t':round(now,2),'event':'prompt_press','direction':current_prompt,'score':last_score})
            elif last_score is None or last_score <= 2:
                if now-last_boot >= 1.0:
                    key='Enter' if int(now)%2==0 else 'ArrowUp'
                    canvas.press(key,delay=180); last_boot=now
                    events.append({'t':round(now,2),'event':'boot_press','key':key,'score':last_score})

            # Handoff only after prompt-free, sustained normal scoring and motion.
            if last_score is not None and len(scores)>=6:
                med_motion=float(np.median(motions)) if motions else 0.0
                recent8=[(t,v) for t,v in scores if now-t<=8.0]
                growth8=(last_score-min(v for _,v in recent8)) if len(recent8)>=5 else 0
                prompt_free=(current_prompt is None and now-last_prompt_seen>=5.0)
                actively_advancing=now-last_change<1.0
                enough_tutorial_evidence=(len(set(seen))>=3 or last_score>=180)
                if prompt_free and actively_advancing and growth8>=18 and med_motion>.0025 and enough_tutorial_evidence:
                    v15.v13.v12.v11.v10.v9.arm_tracker(tracker,last_score)
                    return {
                        'ok':True,'tutorial_completed':True,
                        'startup_controller':'async_prompt_directed_v16',
                        'tutorial_prompt_sequence':seen,
                        'tutorial_events':events[-260:],
                        'score_at_handoff':int(last_score),
                        'recent_score_growth':int(growth8),
                        'motion_median':round(med_motion,6),
                        'valid_score_reads':valid_reads,
                        'policy_clock_reset_after_tutorial':True,
                        'score_hud_xy':[.9275,.0675],
                    }
            time.sleep(.02)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return {
        'ok':False,'reason':'async_prompt_tutorial_timeout',
        'startup_controller':'async_prompt_directed_v16',
        'tutorial_prompt_sequence':seen,
        'tutorial_events':events[-320:],
        'last_prompt_text':last_text,
        'current_prompt':current_prompt,
        'last_score':last_score,'valid_score_reads':valid_reads,
        'recent_score_values':[int(v) for _,v in list(scores)[-60:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
        'seconds_since_last_score_change':round((time.time()-t0)-last_change,2) if last_score is not None else None,
    }

s.startup_and_lock_score = startup_async_prompt_directed

if __name__ == '__main__':
    s.main()
