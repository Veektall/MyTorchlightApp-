#!/usr/bin/env python3
import time
from collections import deque
import numpy as np
import evaluate_stage15_pixel_evaluator_v4 as v4

s=v4.s


def startup_until_score(canvas,tracker,max_sec=38):
    keys=['Space','Enter','ArrowUp','Space','ArrowLeft','ArrowRight','ArrowUp','Space']
    prev=None;motions=deque(maxlen=10);t0=time.time();last_key=-99;valid_reads=0
    while time.time()-t0<max_sec:
        now=time.time()-t0
        png=canvas.screenshot();im=s.pil_from_png(png);_,gray=s.decode_png(png)
        if prev is not None:motions.append(s.mean_abs(gray,prev))
        prev=gray
        if now-last_key>1.4:
            s.focus_canvas(canvas);canvas.press(keys[int(now/1.4)%len(keys)],delay=120);last_key=now
        cands=s.digit_candidates(im)
        if cands:
            valid_reads+=1;tracker.update_search(cands,now)
            if tracker.choose_lock():
                s0=tracker.last_score;proof_t=time.time();proof_motion=[]
                while time.time()-proof_t<3.5:
                    png2=canvas.screenshot();im2=s.pil_from_png(png2);_,g2=s.decode_png(png2)
                    proof_motion.append(s.mean_abs(g2,prev));prev=g2;tracker.read_locked(im2,time.time()-t0);time.sleep(.28)
                if tracker.last_score is not None and s0 is not None and tracker.last_score>=s0+3 and np.median(proof_motion)>.0025:
                    return {'ok':True,'score_start':int(s0),'score_after_proof':int(tracker.last_score),'proof_motion_median':round(float(np.median(proof_motion)),6),'score_hud_xy':[round(tracker.locked['x'],4),round(tracker.locked['y'],4)],'valid_score_reads_before_lock':valid_reads}
        time.sleep(.22)
    dbg=[]
    for tr in tracker.tracks:
        dbg.append([int(v) for _,v in tr['vals'][-12:]])
    return {'ok':False,'reason':'no_verified_endless_play_or_pixel_score_lock','tracks':len(tracker.tracks),'valid_score_reads':valid_reads,'recent_track_values':dbg,'motion_median':round(float(np.median(motions)),6) if motions else 0.0}

s.startup_and_lock_score=startup_until_score

if __name__=='__main__':
    s.main()
