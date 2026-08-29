#!/usr/bin/env python3
import argparse,json,subprocess
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--actions',required=True);ap.add_argument('--video',required=True);ap.add_argument('--source-id',default='official_live_controlled_2026');a=ap.parse_args()
    root=Path(a.root); actions=json.loads(Path(a.actions).read_text()); decisions=actions['decisions']; out=root/'stage6_exact_examples';out.mkdir(parents=True,exist_ok=True)
    selected=[]; last_by_action={};
    # Keep all non-stay actions with spacing; sample stay more sparsely to limit class imbalance.
    for d in decisions:
        act=d['action']; t=float(d['t_sec']); min_gap=.36 if act!='stay' else .75
        if t<.7: continue
        if t-last_by_action.get(act,-99)<min_gap: continue
        if act=='stay':
            # Avoid labeling stay immediately around a physical action.
            if any(abs(float(x['t_sec'])-t)<.45 and x['action']!='stay' for x in decisions): continue
        last_by_action[act]=t;selected.append(d)
    records=[]
    for i,d in enumerate(selected,1):
        t=float(d['t_sec']); start=max(0,t-(8/15)); dur=t-start
        if dur<.40: continue
        p=out/f"{i:05d}-{d['action']}.mp4"
        cmd=['ffmpeg','-y','-v','error','-ss',f'{start:.4f}','-i',a.video,'-t',f'{dur:.4f}','-an','-vf','fps=15,scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2:black','-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',str(p)]
        subprocess.run(cmd,check=True)
        r={'example_id':len(records)+1,'source_id':a.source_id,'action_time_sec':round(t,4),'action':d['action'],'confidence':1.0,'label_origin':'exact_browser_input','eligible_for_training':True,'dataset_role':'exact_action_calibration','context_clip_path':str(p.relative_to(root)),'input_frames':8,'input_fps':15,'input_ends_at_action_onset':True,'privileged_game_state_used':False}
        records.append(r)
    with open(root/'stage6_actions.jsonl','w') as f:
        for r in records:f.write(json.dumps(r,sort_keys=True)+'\n')
    counts={a:sum(r['action']==a for r in records) for a in ['stay','left','right','jump','roll']}
    summary={'stage':'6-exact-action-calibration-v1','source_id':a.source_id,'training_examples':len(records),'counts':counts,'confidence':1.0,'label_origin':'exact_browser_input','rule':'Each example contains only the 8 frames ending at the decision/action onset; no post-action pixels or game internals are policy inputs.'}
    (root/'stage6_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
    if len(records)<20 or sum(counts[x]>0 for x in ['left','right','jump','roll'])<3: raise SystemExit(7)
if __name__=='__main__':main()
