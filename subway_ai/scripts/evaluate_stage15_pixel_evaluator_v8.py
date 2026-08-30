#!/usr/bin/env python3
import re
import time
from collections import deque
import numpy as np
from PIL import ImageOps, ImageEnhance, Image
import pytesseract
import evaluate_stage15_pixel_evaluator_v2 as v2

s=v2.s
TUTORIAL_KEYS=['ArrowUp','ArrowDown','ArrowLeft','ArrowRight']
TUTORIAL_NAMES=['up','down','left','right']


def fast_score_candidate(im):
    """Fast pixel-only read of the verified six-digit upper-right score HUD."""
    w,h=im.size
    roi=im.crop((int(w*.86),int(h*.015),int(w*.995),int(h*.12)))
    g=ImageOps.grayscale(roi).resize((roi.width*5,roi.height*5),Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(2.6)
    reads=[]
    for img in (g,g.point(lambda p:255 if p>150 else 0)):
        try:txt=pytesseract.image_to_string(img,config='--psm 7 -c tessedit_char_whitelist=0123456789')
        except Exception:continue
        d=re.sub(r'\D','',txt)
        if d:
            # Score HUD is exactly six displayed digits. If OCR captures a left-edge artifact,
            # keep the rightmost six; shorter zero-stripped reads still map to the same integer.
            if len(d)>6:d=d[-6:]
            if len(d)<=6:reads.append(d)
            if len(d)==6:break
    if not reads:return []
    # Prefer six-digit read, otherwise the longest available read.
    reads.sort(key=lambda x:(len(x)==6,len(x)),reverse=True)
    try:v=int(reads[0])
    except Exception:return []
    if not (0<=v<=999999):return []
    return [{'value':v,'x':.9275,'y':.0675,'w':.135,'h':.105,'conf':99.0}]


def arm_tracker(tracker,score):
    tracker.tracks=[{'x':.9275,'y':.0675,'w':.135,'h':.105,'vals':[(0.0,int(score))],'conf':[99.0]}]
    tracker.locked=tracker.tracks[0];tracker.last_score=int(score);tracker.last_score_t=0.0


def startup_fast_tutorial(canvas,tracker,max_sec=95):
    t0=time.time();prev=None;motions=deque(maxlen=18);score_hist=deque(maxlen=80)
    last_score=None;last_change=-99.;last_score_read=-99.;last_press=-99.;last_boot=-99.
    stage=0;pressed_for_stage=False;events=[];valid_reads=0

    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
        if prev is not None:motions.append(s.mean_abs(gray,prev))
        prev=gray

        if now-last_score_read>=.42:
            cands=fast_score_candidate(im);last_score_read=now
            if cands:
                val=int(cands[0]['value']);valid_reads+=1;score_hist.append((now,val))
                if last_score is None:
                    last_score=val;last_change=now
                elif val>last_score:
                    old=last_score;last_score=val;last_change=now
                    if pressed_for_stage and stage<len(TUTORIAL_KEYS):
                        events.append({'t':round(now,2),'stage':stage,'direction':TUTORIAL_NAMES[stage],'result':'score_resumed','from':old,'to':val})
                        stage+=1;pressed_for_stage=False
                elif val<last_score and last_score-val>30:
                    # Ignore obvious OCR regression; tracker remains monotonic.
                    pass

        med_motion=float(np.median(motions)) if motions else 0.0
        if last_score is None or last_score<=2:
            if now-last_boot>=1.2:
                s.focus_canvas(canvas);canvas.press('Enter' if int(now/1.2)%2==0 else 'ArrowUp',delay=140);last_boot=now
        else:
            stalled=now-last_change>=1.0
            # Tutorial is early and score-frozen. Repeat the expected arrow at human-like cadence
            # until visible score movement proves that tutorial step was accepted.
            if stalled and last_score<=360 and stage<len(TUTORIAL_KEYS) and now-last_press>=.34:
                key=TUTORIAL_KEYS[stage]
                s.focus_canvas(canvas);canvas.press(key,delay=120);last_press=now;pressed_for_stage=True
                if not events or events[-1].get('press_t')!=round(now,2):
                    events.append({'press_t':round(now,2),'stage':stage,'direction':TUTORIAL_NAMES[stage],'score':last_score})

        if last_score is not None and score_hist:
            recent=[(t,v) for t,v in score_hist if now-t<=5.0]
            growth=(last_score-min(v for _,v in recent)) if len(recent)>=3 else 0
            actively_advancing=now-last_change<.9
            # Allow three-step tutorial variants, but only after substantial post-tutorial score growth.
            tutorial_done=(stage>=4) or (stage>=3 and last_score>=180) or last_score>=280
            if tutorial_done and actively_advancing and growth>=10 and med_motion>.0025:
                arm_tracker(tracker,last_score)
                return {
                    'ok':True,'tutorial_completed':True,'tutorial_steps_completed':stage,
                    'tutorial_events':events[-60:],'score_at_handoff':int(last_score),
                    'recent_score_growth':int(growth),'motion_median':round(med_motion,6),
                    'valid_score_reads':valid_reads,'policy_clock_reset_after_tutorial':True,
                    'score_hud_xy':[.9275,.0675]
                }
        time.sleep(.08)

    return {
        'ok':False,'reason':'fast_tutorial_state_machine_timeout','tutorial_steps_completed':stage,
        'tutorial_events':events[-80:],'last_score':last_score,'valid_score_reads':valid_reads,
        'recent_score_values':[int(v) for _,v in list(score_hist)[-30:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
    }


s.digit_candidates=fast_score_candidate
s.startup_and_lock_score=startup_fast_tutorial

if __name__=='__main__':
    s.main()
