#!/usr/bin/env python3
"""Stage 4: pixel-only maneuver candidate extraction and semantic-label merge.

Optical flow is used only to find maneuver-like change points. It is not trusted
to name every Subway Surfers action. Optional semantic labels from a human or
native-video model are validated against the pixel-derived candidates and the
Stage-3 source quality gate. No DOM/game-state telemetry is read.
"""
import argparse, csv, json, math, subprocess, sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


def load_jsonl(path):
    out=[]
    if not Path(path).exists():
        return out
    with open(path) as f:
        for line in f:
            line=line.strip()
            if line:
                out.append(json.loads(line))
    return out


def robust_z(x):
    x=np.asarray(x,dtype=np.float32)
    med=np.median(x)
    mad=np.median(np.abs(x-med))
    scale=max(1e-3,1.4826*mad)
    return (x-med)/scale


def smooth(x,radius=1):
    x=np.asarray(x,dtype=np.float32)
    if radius<=0 or len(x)<3:
        return x
    k=2*radius+1
    return np.convolve(x,np.ones(k,dtype=np.float32)/k,mode='same')


def decode_gray(path,target=(320,180)):
    cap=cv2.VideoCapture(str(path))
    fps=float(cap.get(cv2.CAP_PROP_FPS) or 15.0)
    frames=[]
    while True:
        ok,bgr=cap.read()
        if not ok:
            break
        g=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
        frames.append(cv2.resize(g,target,interpolation=cv2.INTER_AREA))
    cap.release()
    return fps,frames


def flow_signals(frames):
    if len(frames)<3:
        return []
    h,w=frames[0].shape
    bg=np.zeros((h,w),dtype=bool)
    bg[int(.12*h):int(.78*h),int(.06*w):int(.94*w)]=True
    player=np.zeros((h,w),dtype=bool)
    player[int(.46*h):int(.96*h),int(.22*w):int(.78*w)]=True
    rows=[]
    for i in range(1,len(frames)):
        f=cv2.calcOpticalFlowFarneback(frames[i-1],frames[i],None,0.5,3,15,3,5,1.2,0)
        fx,fy=f[...,0],f[...,1]
        mag=np.sqrt(fx*fx+fy*fy)
        vals=mag[bg]
        th=float(np.percentile(vals,40)) if vals.size else 0.0
        active=bg & (mag>=th)
        if active.sum()<50:
            active=bg
        gdx=float(np.median(fx[active])); gdy=float(np.median(fy[active]))
        vals=mag[player]
        th=float(np.percentile(vals,35)) if vals.size else 0.0
        pact=player & (mag>=th)
        if pact.sum()<30:
            pact=player
        rows.append({
            'frame':i,
            'global_dx':gdx,
            'global_dy':gdy,
            'player_dx_resid':float(np.median(fx[pact])-gdx),
            'player_dy_resid':float(np.median(fy[pact])-gdy),
            'player_energy':float(np.median(mag[pact])),
            'global_energy':float(np.median(mag[active]))
        })
    return rows


def candidate_peaks(signals,fps,threshold=2.15,min_gap_sec=.28):
    if len(signals)<4:
        return []
    gdx=smooth([r['global_dx'] for r in signals],1)
    gdy=smooth([r['global_dy'] for r in signals],1)
    pdx=smooth([r['player_dx_resid'] for r in signals],1)
    pdy=smooth([r['player_dy_resid'] for r in signals],1)
    pe=smooth([r['player_energy'] for r in signals],1)
    dgdy=np.r_[0,np.diff(gdy)]
    dpe=np.r_[0,np.diff(pe)]
    zgdx=robust_z(gdx); zpdx=robust_z(pdx); zpdy=robust_z(pdy)
    zdgdy=robust_z(dgdy); zdpe=robust_z(dpe)
    horiz=np.maximum(np.abs(zgdx),.9*np.abs(zpdx))
    vert=np.maximum(.8*np.abs(zpdy),.55*np.abs(zdgdy))
    energy=.45*np.abs(zdpe)
    score=np.maximum(np.maximum(horiz,vert),energy)
    gap=max(2,int(round(min_gap_sec*fps)))
    peaks=[]
    for i in range(1,len(score)-1):
        if score[i]<threshold or score[i]<score[i-1] or score[i]<score[i+1]:
            continue
        if peaks and i-peaks[-1]['idx']<gap:
            if score[i]>peaks[-1]['score']:
                peaks[-1]={'idx':i,'score':float(score[i])}
            continue
        peaks.append({'idx':i,'score':float(score[i])})
    out=[]
    for p in peaks:
        i=p['idx']; hs=float(horiz[i]); vs=float(vert[i])
        axis='horizontal' if hs>vs*1.2 else ('vertical' if vs>hs*1.2 else 'mixed')
        direction=None
        if axis=='horizontal':
            val=float(pdx[i]) if abs(zpdx[i])>=abs(zgdx[i]) else -float(gdx[i])
            direction='right_like' if val>0 else 'left_like'
        elif axis=='vertical':
            direction='up_like' if float(pdy[i])<0 else 'down_like'
        out.append({
            'local_time_sec':round((i+1)/fps,3),
            'score':round(p['score'],3),
            'axis':axis,
            'provisional_direction':direction,
            'features':{
                'global_dx':round(float(gdx[i]),4),
                'global_dy':round(float(gdy[i]),4),
                'player_dx_resid':round(float(pdx[i]),4),
                'player_dy_resid':round(float(pdy[i]),4),
                'horizontal_z':round(hs,3),
                'vertical_z':round(vs,3)
            }
        })
    return out


def dedupe(cands,tol=.34):
    ranked=sorted(cands,key=lambda x:x['score'],reverse=True)
    kept=[]
    for c in ranked:
        if any(c['source_id']==k['source_id'] and abs(c['time_sec']-k['time_sec'])<=tol for k in kept):
            continue
        kept.append(c)
    return sorted(kept,key=lambda x:(x['source_id'],x['time_sec']))


def extract_window(src,dst,center,pre=.65,post=.75):
    start=max(0.0,center-pre)
    dst.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run([
        'ffmpeg','-y','-v','error','-ss',f'{start:.3f}','-i',str(src),
        '-t',f'{pre+post:.3f}','-an','-c:v','libx264','-preset','veryfast',
        '-crf','27','-pix_fmt','yuv420p',str(dst)
    ],check=True)


def make_sheet(cands,root,out_path):
    if not cands:
        return
    tiles=[]
    for i,c in enumerate(cands[:24]):
        clip=root/c['review_clip_path']
        jpg=root/f'.stage4-thumb-{i}.jpg'
        subprocess.run([
            'ffmpeg','-y','-v','error','-ss','0.65','-i',str(clip),'-frames:v','1',
            '-vf','scale=280:158',str(jpg)
        ],check=True)
        im=Image.open(jpg).convert('RGB')
        can=Image.new('RGB',(280,192),'white'); can.paste(im,(0,0))
        d=ImageDraw.Draw(can)
        d.text((4,162),f"t={c['time_sec']:.2f}s {c['axis']} score={c['score']:.1f}",fill='black')
        d.text((4,177),f"{c.get('provisional_direction') or ''} train={c['eligible_for_training']}",fill='black')
        tiles.append(can); jpg.unlink(missing_ok=True)
    cols=4; rows=math.ceil(len(tiles)/cols)
    sheet=Image.new('RGB',(cols*280,rows*192),'white')
    for i,t in enumerate(tiles):
        sheet.paste(t,((i%cols)*280,(i//cols)*192))
    sheet.save(out_path,quality=90)


def merge_semantic(root,cands,semantic_path,out_path):
    if not semantic_path or not Path(semantic_path).exists():
        return []
    raw=json.loads(Path(semantic_path).read_text())
    if 'events' in raw:
        sid=next(iter({c['source_id'] for c in cands}),'unknown')
        sources={sid:raw}
    else:
        sources=raw.get('sources',raw)
    summary=json.loads((root/'summary.json').read_text())
    meta={s['source_id']:s for s in summary.get('sources',[])}
    rows=[]
    for sid,payload in sources.items():
        if not isinstance(payload,dict):
            continue
        eligible=bool(meta.get(sid,{}).get('training_eligible',False))
        for e in payload.get('events',[]):
            action=str(e.get('action','unknown')).lower()
            if action not in {'left','right','jump','roll','unknown'}:
                action='unknown'
            t=float(e['time_sec']); sem=float(e.get('confidence',0))
            near=min((c for c in cands if c['source_id']==sid),
                     key=lambda c:abs(c['time_sec']-t),default=None)
            delta=abs(near['time_sec']-t) if near else None
            supported=bool(near is not None and delta<=.55)
            conf=max(0.0,min(1.0,sem*(1.0 if supported else .82)))
            rows.append({
                'source_id':sid,'time_sec':round(t,3),'action':action,
                'confidence':round(conf,3),'semantic_confidence':round(sem,3),
                'cv_candidate_supported':supported,
                'cv_time_delta_sec':round(delta,3) if delta is not None else None,
                'visual_evidence':e.get('visual_evidence',''),
                'label_origin':'semantic_video_pixels+cv_candidate' if supported else 'semantic_video_pixels',
                'eligible_for_training':bool(eligible and action!='unknown' and conf>=.75)
            })
        for z in payload.get('stable_no_action_intervals',[]):
            rows.append({
                'source_id':sid,'start_sec':float(z['start_sec']),'end_sec':float(z['end_sec']),
                'action':'stay_interval','confidence':round(float(z.get('confidence',0)),3),
                'label_origin':'semantic_video_pixels','eligible_for_training':False
            })
    with open(out_path,'w') as f:
        for r in rows:
            f.write(json.dumps(r,sort_keys=True)+'\n')
    return rows


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True,help='Stage-3 corpus root')
    ap.add_argument('--semantic-labels',default=None)
    ap.add_argument('--threshold',type=float,default=2.15)
    args=ap.parse_args()
    root=Path(args.root)
    index=load_jsonl(root/'index.jsonl')
    summary=json.loads((root/'summary.json').read_text())
    smeta={s['source_id']:s for s in summary.get('sources',[])}
    review_dir=root/'stage4_review_clips'; review_dir.mkdir(exist_ok=True)
    raw_cands=[]; signal_rows=[]

    for rec in index:
        if not rec.get('accepted'):
            continue
        clip=root/rec['clip_path']
        fps,frames=decode_gray(clip)
        sig=flow_signals(frames)
        for s in sig:
            signal_rows.append({
                'source_id':rec['source_id'],'clip_path':rec['clip_path'],
                'clip_start_sec':rec['start_sec'],
                'time_sec':round(rec['start_sec']+s['frame']/fps,3),**s
            })
        for c in candidate_peaks(sig,fps,args.threshold):
            m=smeta.get(rec['source_id'],{})
            raw_cands.append({
                **c,'source_id':rec['source_id'],'clip_path':rec['clip_path'],
                'clip_start_sec':rec['start_sec'],
                'time_sec':round(rec['start_sec']+c['local_time_sec'],3),
                'eligible_for_training':bool(m.get('training_eligible',False))
            })

    cands=dedupe(raw_cands)
    for i,c in enumerate(cands):
        src=root/c['clip_path']
        local=c['time_sec']-c['clip_start_sec']
        dst=review_dir/f"{c['source_id']}-{i:04d}-{c['time_sec']:.2f}.mp4"
        try:
            extract_window(src,dst,local)
            c['review_clip_path']=str(dst.relative_to(root))
        except Exception:
            c['review_clip_path']=None

    if signal_rows:
        fields=list(signal_rows[0].keys())
        with open(root/'stage4_signals.csv','w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(signal_rows)
    with open(root/'stage4_candidates.jsonl','w') as f:
        for c in cands:
            f.write(json.dumps(c,sort_keys=True)+'\n')
    make_sheet([c for c in cands if c.get('review_clip_path')],root,root/'stage4-contact-sheet.jpg')
    merged=merge_semantic(root,cands,args.semantic_labels,root/'pseudo_actions.jsonl')
    out={
        'stage':'4-pixel-pseudo-action-labeling-v1',
        'candidate_detector':'dense optical-flow change points; semantic action names are not trusted from CV alone',
        'clips_analyzed':sum(1 for r in index if r.get('accepted')),
        'raw_candidates':len(raw_cands),
        'deduped_candidates':len(cands),
        'semantic_labels_merged':sum(1 for r in merged if r.get('action')!='stay_interval'),
        'training_eligible_semantic_labels':sum(1 for r in merged if r.get('eligible_for_training')),
        'quality_rule':'Only Stage-3 training-eligible sources plus non-unknown semantic labels with final confidence >= 0.75 can become training labels.'
    }
    (root/'stage4_summary.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
    if not cands:
        sys.exit(3)

if __name__=='__main__':
    main()
