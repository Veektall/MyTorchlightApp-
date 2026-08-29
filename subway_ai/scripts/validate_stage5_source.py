#!/usr/bin/env python3
import argparse,csv,hashlib,json,math
from pathlib import Path
import cv2,numpy as np

def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def frame_hist(bgr):
    hsv=cv2.cvtColor(bgr,cv2.COLOR_BGR2HSV)
    h=cv2.calcHist([hsv],[0,1],None,[24,24],[0,180,0,256]); cv2.normalize(h,h)
    return h

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--video',required=True); ap.add_argument('--manifest',required=True); ap.add_argument('--source-id',required=True); ap.add_argument('--out',required=True); ap.add_argument('--expected-sha256',default='')
    a=ap.parse_args(); p=Path(a.video); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader(open(a.manifest))); row=next(r for r in rows if r['source_id']==a.source_id)
    cap=cv2.VideoCapture(str(p)); fps=float(cap.get(cv2.CAP_PROP_FPS) or 0); n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0); w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)); dur=n/fps if fps>0 else 0
    step=max(1,int(round(max(fps,1)*0.5)))
    idx=0; prev_g=None; prev_hist=None; diffs=[]; cuts=[]; frozen=[]; freeze_start=None
    while True:
        ok,bgr=cap.read();
        if not ok: break
        if idx%step: idx+=1; continue
        small=cv2.resize(bgr,(160,90),interpolation=cv2.INTER_AREA); g=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY); hist=frame_hist(small)
        if prev_g is not None:
            mad=float(np.mean(cv2.absdiff(prev_g,g))); corr=float(cv2.compareHist(prev_hist,hist,cv2.HISTCMP_CORREL)); t=idx/max(fps,1)
            diffs.append(mad)
            if mad>28 and corr<0.32: cuts.append(round(t,3))
            if mad<0.7:
                if freeze_start is None: freeze_start=t-0.5
            elif freeze_start is not None:
                if t-freeze_start>=2.0: frozen.append([round(freeze_start,3),round(t,3)])
                freeze_start=None
        prev_g,prev_hist=g,hist; idx+=1
    cap.release()
    if freeze_start is not None and dur-freeze_start>=2: frozen.append([round(freeze_start,3),round(dur,3)])
    actual=sha256(p); expected=(a.expected_sha256 or row.get('expected_sha256','')).strip().lower()
    reuse_ok=row.get('reuse_status','').lower() in {'uploader_explicit_free_to_use','explicit_creative_commons_claim','explicit_cc_attribution_claim'}
    checks={
      'hash_match': (not expected) or actual==expected,
      'duration_ge_30s': dur>=30,
      'short_side_ge_480': min(w,h)>=480,
      'fps_ge_24': fps>=24,
      'motion_present': (float(np.median(diffs)) if diffs else 0)>1.2,
      'hard_cut_rate_le_3_per_min': (len(cuts)/max(dur/60,1e-6))<=3.0,
      'no_long_freeze': len(frozen)==0,
      'reuse_verified': reuse_ok,
    }
    eligible=all(checks.values())
    report={'stage':'5-continuous-source-validation-v1','source_id':a.source_id,'video':str(p),'sha256':actual,'expected_sha256':expected or None,'duration_sec':round(dur,3),'width':w,'height':h,'fps':round(fps,3),'median_halfsec_frame_mad':round(float(np.median(diffs)) if diffs else 0,3),'hard_cut_times_sec':cuts,'hard_cuts_per_min':round(len(cuts)/max(dur/60,1e-6),3),'freeze_intervals_sec':frozen,'checks':checks,'training_eligible':eligible}
    (out/'stage5_source_report.json').write_text(json.dumps(report,indent=2))
    # Promote only in a temporary manifest after objective validation.
    fields=list(rows[0].keys())
    with open(out/'stage5_promoted_manifest.csv','w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=fields); wr.writeheader()
        for r in rows:
            rr=dict(r)
            if rr['source_id']==a.source_id: rr['training_eligible']='yes' if eligible else 'no'; rr['auto_ingest']='yes'
            else: rr['auto_ingest']='no'
            wr.writerow(rr)
    print(json.dumps(report,indent=2))
    if not eligible: raise SystemExit(4)
if __name__=='__main__': main()
