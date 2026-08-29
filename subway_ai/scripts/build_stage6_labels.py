#!/usr/bin/env python3
import argparse,csv,json,math,subprocess
from pathlib import Path
import numpy as np

def jl(p):
    if not Path(p).exists(): return []
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]

def rz(x):
    x=np.asarray(x,float); m=np.median(x); mad=np.median(np.abs(x-m)); s=max(.05,1.4826*mad); return (x-m)/s

def extract_context(root,index,event,outdir,fps=15,frames=8):
    t=float(event['time_sec']); need=frames/fps
    options=[r for r in index if r.get('accepted') and r['source_id']==event['source_id'] and r['start_sec']<=t-need and r['start_sec']+r['duration_sec']>=t]
    if not options: return None
    r=min(options,key=lambda z:abs((z['start_sec']+z['duration_sec']/2)-t)); local_start=t-need-r['start_sec']
    src=root/r['clip_path']; dst=outdir/f"{event['source_id']}-{event['event_id']:05d}-{event['action']}.mp4"
    outdir.mkdir(parents=True,exist_ok=True)
    subprocess.run(['ffmpeg','-y','-v','error','-ss',f'{local_start:.3f}','-i',str(src),'-t',f'{need:.3f}','-an','-vf',f'fps={fps}','-c:v','libx264','-preset','veryfast','-crf','25','-pix_fmt','yuv420p',str(dst)],check=True)
    return str(dst.relative_to(root))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ap.add_argument('--stage5-report',required=True); ap.add_argument('--min-confidence',type=float,default=.80); a=ap.parse_args()
    root=Path(a.root); report=json.loads(Path(a.stage5_report).read_text()); eligible=bool(report.get('training_eligible'))
    signals=list(csv.DictReader(open(root/'stage4_signals.csv'))); cands=jl(root/'stage4_candidates.jsonl'); index=jl(root/'index.jsonl')
    cuts=np.array(report.get('hard_cut_times_sec',[]),float)
    # numeric signal arrays per source
    bysrc={}
    for r in signals:
        sid=r['source_id']; bysrc.setdefault(sid,[]).append({k:(float(v) if k not in {'source_id','clip_path'} else v) for k,v in r.items()})
    events=[]; eid=0
    for c in cands:
        sid=c['source_id']; t=float(c['time_sec']); rows=sorted(bysrc.get(sid,[]),key=lambda r:r['time_sec'])
        if len(rows)<8: continue
        if len(cuts) and np.min(np.abs(cuts-t))<.8: continue
        times=np.array([r['time_sec'] for r in rows]); mask=np.abs(times-t)<=.55
        win=[r for r,m in zip(rows,mask) if m]
        if len(win)<6: continue
        dx=np.array([r['player_dx_resid'] for r in win],float); dy=np.array([r['player_dy_resid'] for r in win],float)
        et=np.array([r['time_sec'] for r in win],float)
        peakdx=max(abs(dx).max(),.01); peakdy=max(abs(dy).max(),.01)
        action='unknown'; conf=0.; evidence=''
        axis=c.get('axis')
        if axis=='horizontal':
            j=int(np.argmax(np.abs(dx))); sign=np.sign(dx[j]) or 1; consistent=float(np.mean(np.sign(dx[np.abs(dx)>.35*peakdx])==sign)) if np.any(np.abs(dx)>.35*peakdx) else 0
            displacement=float(abs(dx).sum()); vertical=float(abs(dy).sum())
            if consistent>=.72 and displacement>max(1.0,1.2*vertical):
                action='right' if sign>0 else 'left'; conf=min(.97,.68+.16*min(1,consistent)+.13*min(1,float(c['score'])/5)); evidence=f'horizontal residual flow sign consistency={consistent:.2f}'
        elif axis=='vertical':
            # Subway jump = upward residual followed by downward recovery. Roll = downward impulse followed by upward recovery.
            j=int(np.argmax(np.abs(dy))); s=np.sign(dy[j]) or 1; before=dy[:j+1]; after=dy[j+1:]
            opp=float(np.max(-s*after)) if len(after) else 0.; main=float(np.max(s*before)) if s>0 else float(np.max(-before))
            ratio=opp/max(abs(dy[j]),.05)
            if ratio>=.28:
                # OpenCV y-positive is down.
                action='roll' if s>0 else 'jump'; conf=min(.95,.70+.16*min(1,ratio)+.10*min(1,float(c['score'])/5)); evidence=f'biphasic vertical residual flow recovery_ratio={ratio:.2f}'
        if action=='unknown' or conf<a.min_confidence: continue
        # Estimate onset before peak: first sustained 30%-of-peak motion in same direction.
        arr=dx if action in {'left','right'} else dy; j=int(np.argmax(np.abs(arr))); peak=max(abs(arr[j]),.05); onset=j
        for q in range(j,-1,-1):
            if abs(arr[q])<.30*peak: onset=min(j,q+1); break
            onset=q
        onset_t=float(et[onset])
        eid+=1; events.append({'event_id':eid,'source_id':sid,'time_sec':round(onset_t,3),'candidate_peak_sec':round(t,3),'action':action,'confidence':round(conf,3),'evidence':evidence,'eligible_for_training':eligible,'label_origin':'pixel_temporal_flow_v2','future_frames_used_for_label_inference':True,'training_input_ends_at_action_onset':True})
    # Conservative stay labels: low residual motion and far from all maneuvers/cuts, max 3x maneuver count.
    for sid,rows in bysrc.items():
        times=np.array([r['time_sec'] for r in rows]); dx=np.array([r['player_dx_resid'] for r in rows]); dy=np.array([r['player_dy_resid'] for r in rows]); e=np.array([r['player_energy'] for r in rows]); motion=np.sqrt(rz(dx)**2+rz(dy)**2)+.35*np.abs(rz(e)); thresh=np.quantile(motion,.28)
        maneuver_times=np.array([x['time_sec'] for x in events if x['source_id']==sid],float)
        last=-99.; limit=max(12,3*max(1,len(maneuver_times)))
        for i,t in enumerate(times):
            if len([x for x in events if x['action']=='stay'])>=limit: break
            if t-last<.65 or t<.7: continue
            if motion[i]>thresh: continue
            if len(cuts) and np.min(np.abs(cuts-t))<1.0: continue
            if len(maneuver_times) and np.min(np.abs(maneuver_times-t))<.75: continue
            eid+=1; events.append({'event_id':eid,'source_id':sid,'time_sec':round(float(t),3),'action':'stay','confidence':.9,'evidence':'low player residual motion away from maneuver/cut','eligible_for_training':eligible,'label_origin':'pixel_stable_interval_v1','future_frames_used_for_label_inference':False,'training_input_ends_at_action_onset':True}); last=t
    events=sorted(events,key=lambda x:(x['source_id'],x['time_sec']))
    outdir=root/'stage6_examples'; made=0
    for i,e in enumerate(events,1):
        e['event_id']=i
        try:
            p=extract_context(root,index,e,outdir)
            e['context_clip_path']=p; made+=bool(p)
        except Exception: e['context_clip_path']=None
    with open(root/'stage6_actions.jsonl','w') as f:
        for e in events: f.write(json.dumps(e,sort_keys=True)+'\n')
    counts={k:sum(1 for e in events if e['action']==k) for k in ['left','right','jump','roll','stay']}
    train=[e for e in events if e.get('eligible_for_training') and e.get('context_clip_path')]
    summary={'stage':'6-training-labels-v1','source_training_eligible':eligible,'events_total':len(events),'examples_materialized':made,'training_examples':len(train),'counts':counts,'min_confidence':a.min_confidence,'rule':'Only continuous Stage-5-approved sources; ambiguous events rejected. Labels may use post-onset pixels for inference, but each training context ends at the estimated action onset to prevent action-after-the-fact leakage.'}
    (root/'stage6_summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary,indent=2))
    if eligible and len(train)<8: raise SystemExit(6)
if __name__=='__main__': main()
