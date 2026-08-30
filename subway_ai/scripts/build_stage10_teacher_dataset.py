#!/usr/bin/env python3
import argparse, json
from collections import Counter
from pathlib import Path
import cv2, numpy as np
ACTIONS=['stay','left','right','jump','roll']
MIN_EPISODES=6; MIN_PER_CLASS=25; MIN_COVERAGE=4

def frame_at(cap,t):
    cap.set(cv2.CAP_PROP_POS_MSEC,max(0,t)*1000);ok,bgr=cap.read()
    if not ok:return None
    rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    h,w=rgb.shape[:2];mx=max(0,int(w*.008));my=max(0,int(h*.014));rgb=rgb[my:h-my if my else h,mx:w-mx if mx else w]
    return cv2.resize(rgb,(96,54),interpolation=cv2.INTER_AREA)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--teacher-root',required=True);ap.add_argument('--root',required=True);args=ap.parse_args()
    tr=Path(args.teacher_root);root=Path(args.root);root.mkdir(parents=True,exist_ok=True);ex=root/'stage10_exact_rgb8';ex.mkdir(exist_ok=True)
    summary=json.loads((tr/'stage10_teacher_summary.json').read_text());episodes=[e for e in summary['episodes'] if e.get('accepted')]
    records=[];last={};ep_counts={}
    for ep in episodes:
        video=Path(ep['video_path']);actions=json.loads(Path(ep['actions_path']).read_text())['decisions'];cap=cv2.VideoCapture(str(video));ec=Counter()
        if not cap.isOpened():continue
        for d in actions:
            a=d['action'];conf=float(d.get('teacher_confidence',1));t=float(d['t_sec'])
            if conf<.60:continue
            key=(ep['episode_id'],a);gap=.68 if a!='stay' else 1.0
            if t-last.get(key,-99)<gap:continue
            end=.700+t-.100;start=end-7/15
            if start<0:continue
            frames=[]
            for ts in np.linspace(start,end,8):
                fr=frame_at(cap,float(ts))
                if fr is None:frames=[];break
                frames.append(fr)
            if len(frames)!=8:continue
            arr=np.stack(frames).astype(np.uint8);eid=len(records)+1;rel=f'stage10_exact_rgb8/{eid:05d}-{ep["episode_id"]}-{a}.rgb8';arr.tofile(root/rel)
            records.append({'example_id':eid,'episode_id':ep['episode_id'],'action':a,'teacher_confidence':conf,'teacher_reason':d.get('teacher_reason'),'example_path':rel,'input_frames':8,'input_size':[8,54,96,3],'input_ends_before_action_onset':True,'label_origin':'exact_browser_input_from_semantic_pixel_teacher','privileged_game_state_used':False,'policy_contract':'pixel-policy-contract-v1.1'});last[key]=t;ec[a]+=1
        cap.release();ep_counts[ep['episode_id']]=dict(ec)
    with (root/'stage10_examples.jsonl').open('w') as f:
        for r in records:f.write(json.dumps(r,sort_keys=True)+'\n')
    counts=Counter(r['action'] for r in records);coverage={a:len({r['episode_id'] for r in records if r['action']==a}) for a in ACTIONS};usable=len({r['episode_id'] for r in records})
    accepted=usable>=MIN_EPISODES and all(counts[a]>=MIN_PER_CLASS for a in ACTIONS) and all(coverage[a]>=MIN_COVERAGE for a in ACTIONS)
    out={'stage':'10-semantic-pixel-teacher-dataset-v1','examples_total':len(records),'usable_episode_count':usable,'counts':{a:counts[a] for a in ACTIONS},'episode_coverage_by_action':coverage,'episode_counts':ep_counts,'input':'8 pre-action RGB frames from official rendered gameplay -> 96x54','label_origin':'exact trusted key selected by pixel-only teacher','acceptance_gate':{'min_episodes':MIN_EPISODES,'min_examples_per_class':MIN_PER_CLASS,'min_episode_coverage_per_action':MIN_COVERAGE},'privileged_game_state_used':False,'accepted':accepted};(root/'stage10_dataset_summary.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
    if not accepted:raise SystemExit(12)
if __name__=='__main__':main()
