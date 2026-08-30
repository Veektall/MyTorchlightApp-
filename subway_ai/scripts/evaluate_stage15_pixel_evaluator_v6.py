#!/usr/bin/env python3
import re
import time
from collections import deque
import numpy as np
import evaluate_stage15_pixel_evaluator_v5 as v5

s=v5.s

PROMPT_KEYS={
    'up':'ArrowUp',
    'down':'ArrowDown',
    'left':'ArrowLeft',
    'right':'ArrowRight',
}


def tutorial_direction(text):
    """Infer only an explicitly rendered tutorial arrow request from canvas OCR."""
    t=' '.join((text or '').lower().split())
    # Require tutorial/instruction context so ordinary scene text cannot trigger actions.
    instruction=any(k in t for k in ('press','arrow key','arrow','swipe','jump','roll'))
    if not instruction:
        return None
    # Prefer explicit arrow-key wording; tolerate OCR dropping punctuation/case.
    for d in ('up','down','left','right'):
        if re.search(rf'(arrow\s*(key\s*)?{d}|{d}\s*arrow|swipe\s*{d})',t):
            return d
    if 'jump' in t:return 'up'
    if 'roll' in t:return 'down'
    return None


def _arm_tracker(tracker,score):
    tracker.tracks=[{'x':.9275,'y':.0675,'w':.135,'h':.105,'vals':[(0.0,int(score))],'conf':[99.0]}]
    tracker.locked=tracker.tracks[0]
    tracker.last_score=int(score)
    # Policy loop starts its own t=0; death/score-stall logic must use that clock.
    tracker.last_score_t=0.0


def startup_tutorial_aware(canvas,tracker,max_sec=85):
    """Complete rendered tutorial prompts, then prove uncensored endless play.

    Environment setup may press Enter/Up to leave menus before a tutorial prompt exists,
    but once a rendered tutorial direction is visible only that requested arrow is sent.
    All decisions are derived from canvas pixels/OCR; no DOM/game state is consulted.
    """
    t0=time.time();prev=None;motions=deque(maxlen=14);score_hist=deque(maxlen=80)
    tutorial_events=[];seen=set();last_prompt_t=-99.;last_prompt_dir=None;last_prompt_press=-99.
    last_boot=-99.;last_ocr=-99.;last_text='';valid_reads=0

    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
        if prev is not None:motions.append(s.mean_abs(gray,prev))
        prev=gray

        # Fixed six-digit HUD score, from rendered pixels only.
        cands=s.digit_candidates(im)
        if cands:
            val=int(cands[0]['value']);valid_reads+=1;score_hist.append((now,val))

        if now-last_ocr>=.42:
            last_text=s.ocr_text(im);last_ocr=now
        direction=tutorial_direction(last_text)
        if direction:
            last_prompt_t=now;last_prompt_dir=direction;seen.add(direction)
            # Re-send if the tutorial remains frozen; trusted ordinary arrow input only.
            if now-last_prompt_press>=.72:
                s.focus_canvas(canvas);canvas.press(PROMPT_KEYS[direction],delay=180)
                tutorial_events.append({'t':round(now,2),'direction':direction,'key':PROMPT_KEYS[direction]})
                last_prompt_press=now
        elif not score_hist or (score_hist and max(v for _,v in score_hist)<=3):
            # Menu/startup only. Avoid Space so hoverboard state cannot leak into evaluation.
            if now-last_boot>=1.7:
                s.focus_canvas(canvas)
                canvas.press('Enter' if int(now/1.7)%2==0 else 'ArrowUp',delay=160)
                last_boot=now

        # Prove we are beyond tutorial: no prompt recently, moving scene, and score growth.
        if score_hist:
            current=score_hist[-1][1]
            recent=[(t,v) for t,v in score_hist if now-t<=5.5]
            growth=(current-min(v for _,v in recent)) if len(recent)>=3 else 0
            med_motion=float(np.median(motions)) if motions else 0.0
            prompt_clear=now-last_prompt_t>=4.0
            tutorial_coverage=(len(seen)>=3) or (current>=120 and now-last_prompt_t>=7.0)
            if prompt_clear and tutorial_coverage and growth>=8 and med_motion>.0025:
                _arm_tracker(tracker,current)
                return {
                    'ok':True,
                    'tutorial_completed':True,
                    'tutorial_directions_seen':sorted(seen),
                    'tutorial_events':tutorial_events,
                    'score_at_handoff':int(current),
                    'recent_score_growth':int(growth),
                    'motion_median':round(med_motion,6),
                    'valid_score_reads':valid_reads,
                    'score_hud_xy':[.9275,.0675],
                    'policy_clock_reset_after_tutorial':True,
                }
        time.sleep(.16)

    return {
        'ok':False,
        'reason':'tutorial_not_cleared_or_score_not_advancing',
        'tutorial_directions_seen':sorted(seen),
        'tutorial_events':tutorial_events,
        'last_prompt_direction':last_prompt_dir,
        'last_ocr_text':last_text[-300:],
        'valid_score_reads':valid_reads,
        'recent_score_values':[int(v) for _,v in list(score_hist)[-20:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
    }


s.startup_and_lock_score=startup_tutorial_aware

if __name__=='__main__':
    s.main()
