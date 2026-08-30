#!/usr/bin/env python3
import time
from collections import deque
import numpy as np
import evaluate_stage15_pixel_evaluator_v10 as v10

s = v10.s
SWEEP = [('up','ArrowUp'),('down','ArrowDown'),('left','ArrowLeft'),('right','ArrowRight')]


def startup_burst_sweep(canvas, tracker, max_sec=95):
    t0=time.time(); prev=None; motions=deque(maxlen=24); scores=deque(maxlen=160)
    last_score=None; last_change=-99.; last_score_read=-99.; last_action=-99.; last_boot=-99.
    direction_i=0; bursts_on_direction=0; events=[]; valid_reads=0; stall_started=None; last_stall=-99.

    while time.time()-t0 < max_sec:
        now=time.time()-t0
        png=canvas.screenshot(); im=s.pil_from_png(png); _,gray=s.decode_png(png)
        if prev is not None: motions.append(s.mean_abs(gray,prev))
        prev=gray

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

        if last_score is None or last_score <= 2:
            if now-last_boot >= .9:
                s.focus_canvas(canvas); key='Enter' if int(now/.9)%2==0 else 'ArrowUp'
                canvas.press(key,delay=80); last_boot=now
                events.append({'t':round(now,2),'event':'boot_press','key':key,'score':last_score})
        else:
            stalled = now-last_change >= 1.15
            if stalled and last_score < 500:
                if stall_started is None:
                    stall_started=now; events.append({'t':round(now,2),'event':'stall_enter','score':last_score})
                    # Restart at Up for each new tutorial checkpoint; dense blocks advance quickly.
                    direction_i=0; bursts_on_direction=0
                last_stall=now
                if now-last_action >= .38:
                    name,key=SWEEP[direction_i % 4]
                    s.focus_canvas(canvas)
                    for _ in range(4): canvas.press(key,delay=45)
                    last_action=now; bursts_on_direction += 1
                    events.append({'t':round(now,2),'event':'burst_press','direction':name,'count':4,'score':last_score})
                    if bursts_on_direction >= 2:
                        direction_i=(direction_i+1)%4; bursts_on_direction=0
            else:
                if stall_started is not None and now-last_change < .8:
                    events.append({'t':round(now,2),'event':'stall_released','score':last_score,'stall_sec':round(now-stall_started,2)})
                    stall_started=None; direction_i=0; bursts_on_direction=0

        if last_score is not None and len(scores)>=4:
            med_motion=float(np.median(motions)) if motions else 0.0
            recent6=[(t,v) for t,v in scores if now-t<=6.0]
            growth6=(last_score-min(v for _,v in recent6)) if len(recent6)>=4 else 0
            uninterrupted = now-last_stall >= 7.0
            actively_advancing = now-last_change < .85
            if last_score >= 160 and uninterrupted and actively_advancing and growth6 >= 18 and med_motion > .0025:
                v10.v9.arm_tracker(tracker,last_score)
                return {
                    'ok':True,'tutorial_completed':True,
                    'startup_controller':'pixel_score_stall_dense_direction_bursts_v11',
                    'tutorial_events':events[-160:],'score_at_handoff':int(last_score),
                    'recent_score_growth':int(growth6),'seconds_since_last_tutorial_stall':round(now-last_stall,2),
                    'motion_median':round(med_motion,6),'valid_score_reads':valid_reads,
                    'policy_clock_reset_after_tutorial':True,'score_hud_xy':[.9275,.0675]
                }
        time.sleep(.025)

    return {
        'ok':False,'reason':'dense_burst_tutorial_timeout',
        'startup_controller':'pixel_score_stall_dense_direction_bursts_v11',
        'tutorial_events':events[-220:],'last_score':last_score,'valid_score_reads':valid_reads,
        'recent_score_values':[int(v) for _,v in list(scores)[-40:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
        'seconds_since_last_score_change':round((time.time()-t0)-last_change,2) if last_score is not None else None,
    }


s.startup_and_lock_score = startup_burst_sweep

if __name__ == '__main__':
    s.main()
