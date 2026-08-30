#!/usr/bin/env python3
import time
from collections import deque
import numpy as np
from PIL import ImageOps, ImageEnhance, Image
import pytesseract
import evaluate_stage15_pixel_evaluator_v6 as v6

s=v6.s
PROMPT_KEYS=v6.PROMPT_KEYS
FALLBACK_ORDER=['up','down','left','right']


def center_prompt_text(im):
    w,h=im.size
    # Tutorial instruction is rendered near canvas center. OCR it separately from HUD/scenery.
    roi=im.crop((int(w*.20),int(h*.32),int(w*.82),int(h*.72)))
    g=ImageOps.grayscale(roi).resize((roi.width*4,roi.height*4),Image.Resampling.BICUBIC)
    variants=[ImageEnhance.Contrast(g).enhance(2.8),g.point(lambda p:255 if p>155 else 0)]
    reads=[]
    for v in variants:
        for psm in (6,11,12):
            try:reads.append(pytesseract.image_to_string(v,config=f'--psm {psm}',lang='eng'))
            except Exception:pass
    return ' '.join(reads).lower()


def _arm_tracker(tracker,score):
    tracker.tracks=[{'x':.9275,'y':.0675,'w':.135,'h':.105,'vals':[(0.0,int(score))],'conf':[99.0]}]
    tracker.locked=tracker.tracks[0];tracker.last_score=int(score);tracker.last_score_t=0.0


def startup_tutorial_feedback(canvas,tracker,max_sec=110):
    t0=time.time();prev=None;motions=deque(maxlen=16);scores=deque(maxlen=120)
    tutorial_events=[];seen=set();last_prompt_t=-99.;last_press=-99.;last_boot=-99.;last_prompt_ocr=-99.
    last_text='';last_score=None;last_score_change_t=-99.;pending_dir=None;pending_score=None;fallback_i=0;valid_reads=0

    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
        if prev is not None:motions.append(s.mean_abs(gray,prev))
        prev=gray

        cands=s.digit_candidates(im)
        if cands:
            val=int(cands[0]['value']);valid_reads+=1;scores.append((now,val))
            if last_score is None or val>last_score:
                # A pending fallback/explicit arrow is only credited if visible score resumes.
                if pending_dir is not None and pending_score is not None and val>pending_score:
                    seen.add(pending_dir)
                    tutorial_events.append({'t':round(now,2),'direction':pending_dir,'result':'score_resumed','score':val})
                    pending_dir=None;pending_score=None;fallback_i=0
                last_score=val;last_score_change_t=now

        if now-last_prompt_ocr>=.45:
            last_text=center_prompt_text(im);last_prompt_ocr=now
        explicit=v6.tutorial_direction(last_text)

        if explicit:
            last_prompt_t=now
            if now-last_press>=.72:
                s.focus_canvas(canvas);canvas.press(PROMPT_KEYS[explicit],delay=180)
                pending_dir=explicit;pending_score=last_score
                tutorial_events.append({'t':round(now,2),'direction':explicit,'result':'explicit_prompt_press','score':last_score})
                last_press=now
        elif last_score is None or last_score<=3:
            if now-last_boot>=1.6:
                s.focus_canvas(canvas);canvas.press('Enter' if int(now/1.6)%2==0 else 'ArrowUp',delay=160);last_boot=now
        else:
            # Pixel-only tutorial fallback: early score is frozen while the scene still animates.
            # Try one arrow at a time; only a key followed by score growth is considered successful.
            med_motion=float(np.median(motions)) if motions else 0.0
            stalled=now-last_score_change_t>=1.35
            early=last_score<=320
            if early and stalled and med_motion>.01 and now-last_press>=.85:
                d=FALLBACK_ORDER[fallback_i%len(FALLBACK_ORDER)];fallback_i+=1
                s.focus_canvas(canvas);canvas.press(PROMPT_KEYS[d],delay=180)
                pending_dir=d;pending_score=last_score;last_press=now;last_prompt_t=now
                tutorial_events.append({'t':round(now,2),'direction':d,'result':'stall_probe_press','score':last_score})

        if scores and last_score is not None:
            recent=[(t,v) for t,v in scores if now-t<=5.5]
            growth=(last_score-min(v for _,v in recent)) if len(recent)>=3 else 0
            med_motion=float(np.median(motions)) if motions else 0.0
            actively_advancing=now-last_score_change_t<1.0
            prompt_clear=now-last_prompt_t>=3.0 and v6.tutorial_direction(last_text) is None
            tutorial_finished=(len(seen)>=4) or last_score>=220
            if tutorial_finished and prompt_clear and actively_advancing and growth>=8 and med_motion>.0025:
                _arm_tracker(tracker,last_score)
                return {
                    'ok':True,'tutorial_completed':True,
                    'tutorial_directions_seen':sorted(seen),'tutorial_events':tutorial_events,
                    'score_at_handoff':int(last_score),'recent_score_growth':int(growth),
                    'motion_median':round(med_motion,6),'valid_score_reads':valid_reads,
                    'policy_clock_reset_after_tutorial':True,'score_hud_xy':[.9275,.0675]
                }
        time.sleep(.14)

    return {
        'ok':False,'reason':'tutorial_feedback_state_machine_timeout',
        'tutorial_directions_seen':sorted(seen),'tutorial_events':tutorial_events[-40:],
        'last_prompt_text':last_text[-500:],'last_score':last_score,
        'valid_score_reads':valid_reads,'recent_score_values':[int(v) for _,v in list(scores)[-30:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
    }


s.startup_and_lock_score=startup_tutorial_feedback

if __name__=='__main__':
    s.main()
