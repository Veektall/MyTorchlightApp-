#!/usr/bin/env python3
import re
import time
from collections import deque
import numpy as np
from PIL import ImageOps, ImageEnhance, Image
import pytesseract
import evaluate_stage15_pixel_evaluator_v2 as v2

s=v2.s
PROMPT_KEY={'up':'ArrowUp','down':'ArrowDown','left':'ArrowLeft','right':'ArrowRight'}


def fast_score_candidate(im):
    w,h=im.size
    roi=im.crop((int(w*.86),int(h*.015),int(w*.995),int(h*.12)))
    g=ImageOps.grayscale(roi).resize((roi.width*5,roi.height*5),Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(2.6)
    for img in (g,g.point(lambda p:255 if p>150 else 0)):
        try:txt=pytesseract.image_to_string(img,config='--psm 7 -c tessedit_char_whitelist=0123456789')
        except Exception:continue
        d=re.sub(r'\D','',txt)
        if not d:continue
        if len(d)>6:d=d[-6:]
        try:v=int(d)
        except Exception:continue
        if 0<=v<=999999:return [{'value':v,'x':.9275,'y':.0675,'w':.135,'h':.105,'conf':99.0}]
    return []


def prompt_text(im):
    w,h=im.size
    roi=im.crop((int(w*.20),int(h*.34),int(w*.82),int(h*.70)))
    g=ImageOps.grayscale(roi).resize((roi.width*3,roi.height*3),Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(2.8)
    try:return pytesseract.image_to_string(g,config='--psm 11',lang='eng').lower()
    except Exception:return ''


def prompt_direction(text):
    n=' '.join(re.sub(r'[^a-z]+',' ',(text or '').lower()).split())
    if not any(k in n for k in ('arrow','press','swipe','jump','roll')):return None
    if 'up' in n or 'jump' in n:return 'up'
    if 'down' in n or 'roll' in n:return 'down'
    if 'left' in n:return 'left'
    if 'right' in n:return 'right'
    return None


def tight_read_locked(self,im,t):
    cands=fast_score_candidate(im)
    if not cands:return self.last_score
    v=int(cands[0]['value']);last=self.last_score
    if last is None:
        self.last_score=v;self.last_score_t=t;return v
    # HUD score changes smoothly. Reject OCR hallucinations such as 000061 -> 900061.
    if v<max(0,last-3) or v>last+500:return last
    if v>last:self.last_score=v;self.last_score_t=t
    return self.last_score


def arm_tracker(tracker,score):
    tracker.tracks=[{'x':.9275,'y':.0675,'w':.135,'h':.105,'vals':[(0.0,int(score))],'conf':[99.0]}]
    tracker.locked=tracker.tracks[0];tracker.last_score=int(score);tracker.last_score_t=0.0


def startup_prompt_authoritative(canvas,tracker,max_sec=125):
    t0=time.time();prev=None;motions=deque(maxlen=18);scores=deque(maxlen=100)
    last_score=None;last_change=-99.;last_score_read=-99.;last_prompt_read=-99.;last_press=-99.;last_boot=-99.
    last_prompt_seen=-99.;current_prompt=None;last_prompt_text='';seen=[];events=[];valid_reads=0

    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
        if prev is not None:motions.append(s.mean_abs(gray,prev))
        prev=gray

        if now-last_score_read>=.45:
            c=fast_score_candidate(im);last_score_read=now
            if c:
                v=int(c[0]['value']);valid_reads+=1
                if last_score is None:
                    last_score=v;last_change=now
                elif v>=last_score and v<=last_score+500:
                    if v>last_score:last_change=now
                    last_score=v
                scores.append((now,last_score if last_score is not None else v))

        if now-last_prompt_read>=.55:
            last_prompt_text=prompt_text(im);last_prompt_read=now
            d=prompt_direction(last_prompt_text)
            if d:
                current_prompt=d;last_prompt_seen=now
                if not seen or seen[-1]!=d:seen.append(d);events.append({'t':round(now,2),'event':'prompt_seen','direction':d,'score':last_score})
            elif now-last_prompt_seen>2.0:
                current_prompt=None

        if current_prompt:
            if now-last_press>=.28:
                s.focus_canvas(canvas);s_key=PROMPT_KEY[current_prompt];canvas.press(s_key,delay=110);last_press=now
                events.append({'t':round(now,2),'event':'prompt_press','direction':current_prompt,'score':last_score})
        elif last_score is None or last_score<=2:
            if now-last_boot>=1.25:
                s.focus_canvas(canvas);canvas.press('Enter' if int(now/1.25)%2==0 else 'ArrowUp',delay=140);last_boot=now

        if last_score is not None and scores:
            recent=[(t,v) for t,v in scores if now-t<=5.0]
            growth=(last_score-min(v for _,v in recent)) if len(recent)>=3 else 0
            med_motion=float(np.median(motions)) if motions else 0.0
            prompt_clear=now-last_prompt_seen>=4.0 and current_prompt is None
            actively_advancing=now-last_change<1.0
            # Do not hand off between tutorial prompts. Require substantial post-tutorial progress
            # or at least three distinct rendered direction phases.
            coverage=(len(set(seen))>=3 and last_score>=140) or last_score>=220
            if prompt_clear and actively_advancing and growth>=10 and coverage and med_motion>.0025:
                arm_tracker(tracker,last_score)
                return {
                    'ok':True,'tutorial_completed':True,'tutorial_prompt_sequence':seen,
                    'tutorial_events':events[-100:],'score_at_handoff':int(last_score),
                    'recent_score_growth':int(growth),'motion_median':round(med_motion,6),
                    'valid_score_reads':valid_reads,'policy_clock_reset_after_tutorial':True,
                    'score_hud_xy':[.9275,.0675]
                }
        time.sleep(.06)

    return {
        'ok':False,'reason':'prompt_authoritative_tutorial_timeout','tutorial_prompt_sequence':seen,
        'tutorial_events':events[-120:],'last_prompt_text':last_prompt_text[-500:],
        'current_prompt':current_prompt,'last_score':last_score,'valid_score_reads':valid_reads,
        'recent_score_values':[int(v) for _,v in list(scores)[-30:]],
        'motion_median':round(float(np.median(motions)),6) if motions else 0.0,
    }


s.digit_candidates=fast_score_candidate
s.ScoreTracker.read_locked=tight_read_locked
s.startup_and_lock_score=startup_prompt_authoritative

if __name__=='__main__':
    s.main()
