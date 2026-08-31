#!/usr/bin/env python3
"""Offline replay benchmark for stage15_prompt_template_detector.py.

Inputs are the downloaded v24/v25 `stage15_session.webm` artifacts. Ground-truth timestamps were
manually curated by visual inspection of saved frames. The harness tries only known recording
layout crops (full canvas, Poki-embedded canvas, top-left canvas); the production detector itself
receives the canvas screenshot directly and does not need this layout normalization.
"""
from __future__ import annotations
import argparse, json, statistics, time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps
import pytesseract

from stage15_prompt_template_detector import score_prompt_direction

V25_POS=[(84,"up"),(85,"up"),(90,"up"),(92,"up"),(106,"down"),(107,"down"),
         (138,"down"),(174,"left"),(1072,"right"),(1077,"right")]
V24_POS=[(30,"up"),(150,"down"),(223,"down"),(300,"left"),(400,"left")]
V25_NEG=[82,160,165,250,500,900,1085,1110]
V24_NEG=[10,60,100,250,280,350,500,590,600]

def percentile(xs,p):
    xs=sorted(xs); idx=(len(xs)-1)*p; lo=int(idx); hi=min(lo+1,len(xs)-1); f=idx-lo
    return xs[lo]*(1-f)+xs[hi]*f

def frame_at(video,t):
    cap=cv2.VideoCapture(str(video)); cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000.0)
    ok,bgr=cap.read(); cap.release()
    if not ok: raise RuntimeError(f"cannot read {video} at {t}s")
    return cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)

def recording_canvas_candidates(frame):
    h,w=frame.shape[:2]
    out=[("full",frame)]
    if h>=486 and w>=997:
        out.append(("embedded",frame[16:486,160:997]))
    if h>=470 and w>=837:
        out.append(("top_left",frame[:470,:837]))
    return out

def best_candidate(frame):
    scored=[]
    for mode,canvas in recording_canvas_candidates(frame):
        det=score_prompt_direction(canvas)
        scored.append((det.presence_score,mode,canvas,det))
    return max(scored,key=lambda x:x[0])

def broad_ocr(canvas):
    im=Image.fromarray(canvas)
    w,h=im.size
    roi=im.crop((int(w*.24),int(h*.36),int(w*.78),int(h*.68)))
    g=ImageOps.grayscale(roi).resize((roi.width*2,roi.height*2),Image.Resampling.BICUBIC)
    g=ImageEnhance.Contrast(g).enhance(2.6)
    return pytesseract.image_to_string(g,config="--psm 11",lang="eng")

def run(video,positives,negatives,name):
    positive_rows=[]; negative_rows=[]; canvases=[]
    for t,label in positives:
        score,mode,canvas,det=best_candidate(frame_at(video,t))
        positive_rows.append({
            "t":t,"expected":label,"detected":det.direction,"correct":det.direction==label,
            "presence":round(det.presence_score,4),"suffix":round(det.suffix_score,4),
            "margin":round(det.suffix_margin,4),"recording_layout":mode,
        })
        canvases.append(canvas)
    for t in negatives:
        score,mode,canvas,det=best_candidate(frame_at(video,t))
        negative_rows.append({
            "t":t,"detected":det.direction,"false_positive":det.direction is not None,
            "presence":round(det.presence_score,4),"suffix":round(det.suffix_score,4),
            "margin":round(det.suffix_margin,4),"recording_layout":mode,
        })
        canvases.append(canvas)
    return {
        "name":name,
        "positive_rows":positive_rows,
        "negative_rows":negative_rows,
        "positive_correct":sum(r["correct"] for r in positive_rows),
        "positive_total":len(positive_rows),
        "false_positives":sum(r["false_positive"] for r in negative_rows),
        "negative_total":len(negative_rows),
        "canvases":canvases,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v24",required=True)
    ap.add_argument("--v25",required=True)
    ap.add_argument("--out")
    ap.add_argument("--skip-ocr-baseline",action="store_true")
    a=ap.parse_args()

    v25=run(a.v25,V25_POS,V25_NEG,"v25")
    v24=run(a.v24,V24_POS,V24_NEG,"v24")
    canvases=v25.pop("canvases")+v24.pop("canvases")

    for c in canvases[:2]: score_prompt_direction(c)
    dt=[]
    for _ in range(5):
        for c in canvases:
            st=time.perf_counter(); score_prompt_direction(c); dt.append((time.perf_counter()-st)*1000)
    latency={
        "n":len(dt),"median_ms":statistics.median(dt),"mean_ms":statistics.mean(dt),
        "p95_ms":percentile(dt,.95),"max_ms":max(dt),
    }

    baseline=None
    if not a.skip_ocr_baseline:
        broad_ocr(canvases[0])
        bt=[]
        for c in canvases[:8]:
            st=time.perf_counter(); broad_ocr(c); bt.append((time.perf_counter()-st)*1000)
        baseline={
            "n":len(bt),"median_ms":statistics.median(bt),"mean_ms":statistics.mean(bt),
            "p95_ms":percentile(bt,.95),"max_ms":max(bt),
            "median_speedup_x":statistics.median(bt)/statistics.median(dt),
        }

    out={
        "detector":"stage15_prompt_template_detector",
        "ground_truth":"manually curated visible prompt / prompt-absent frames from v24 and v25 recordings",
        "v24":v24,"v25":v25,
        "aggregate":{
            "positive_correct":v24["positive_correct"]+v25["positive_correct"],
            "positive_total":v24["positive_total"]+v25["positive_total"],
            "false_positives":v24["false_positives"]+v25["false_positives"],
            "negative_total":v24["negative_total"]+v25["negative_total"],
        },
        "detector_latency":latency,
        "broad_tesseract_latency":baseline,
    }
    text=json.dumps(out,indent=2)
    if a.out: Path(a.out).write_text(text)
    print(text)

if __name__=="__main__":
    main()
