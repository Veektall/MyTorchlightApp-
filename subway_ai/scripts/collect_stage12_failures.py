#!/usr/bin/env python3
import argparse,json,time
from collections import deque,Counter
from pathlib import Path
import cv2,numpy as np,torch
from playwright.sync_api import sync_playwright
from stage10_v4_model import Stage10Policy,ACTIONS
from eval_stage11_closed_loop import open_game,decode_png,death,profiles,corridor_choose,model_input,KEYS

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--episodes',type=int,default=5);ap.add_argument('--seconds',type=int,default=45);args=ap.parse_args();root=Path(args.root);outdir=root/'stage12_failure_rgb8';outdir.mkdir(exist_ok=True)
    ck=torch.load(root/'stage10_imitation_policy.pt',map_location='cpu');m=Stage10Policy();m.load_state_dict(ck['model']);m.eval();records=[];eps=[]
    with sync_playwright() as p:
        for ei in range(1,args.episodes+1):
            eid=f'stage12_selfplay_ep{ei:02d}';pending=deque(maxlen=24);t0=time.time();lane=1;prev=None;buf=deque(maxlen=8);acts=Counter();dead=False
            try:
                browser,ctx,page,canvas=open_game(p)
                while time.time()-t0<args.seconds:
                    rgb,g=decode_png(canvas.screenshot())
                    if death(rgb):dead=True;break
                    buf.append(rgb)
                    if len(buf)<8:time.sleep(.07);continue
                    x=model_input(buf)
                    with torch.no_grad():prob=m(x).softmax(1)[0];li=int(prob.argmax().item());la=ACTIONS[li];lc=float(prob[li])
                    teacher=corridor_choose(profiles(g,prev),lane)
                    if teacher!=la and teacher!='stay':
                        arr=np.stack([cv2.resize(z,(96,54),interpolation=cv2.INTER_AREA) for z in buf]).astype(np.uint8)
                        pending.append({'frames':arr,'learned_action':la,'teacher_action':teacher,'learned_confidence':lc,'t_sec':time.time()-t0,'lane_estimate':lane})
                    if la!='stay':canvas.press(KEYS[la],delay=180)
                    if la=='left':lane=max(0,lane-1)
                    elif la=='right':lane=min(2,lane+1)
                    acts[la]+=1;prev=g;time.sleep(.10)
            except Exception as e:
                eps.append({'episode_id':eid,'error':str(e),'duration_sec':round(time.time()-t0,3),'death_detected':True,'action_counts':dict(acts),'candidate_disagreements':len(pending)});continue
            finally:
                try:ctx.close();browser.close()
                except Exception:pass
            kept=list(pending) if dead else list(pending)[-8:]
            for q in kept:
                i=len(records)+1;rel=f'stage12_failure_rgb8/{i:05d}-{eid}-{q["teacher_action"]}.rgb8';q['frames'].tofile(root/rel);records.append({'example_id':i,'episode_id':eid,'action':q['teacher_action'],'learned_action':q['learned_action'],'learned_confidence':round(q['learned_confidence'],4),'example_path':rel,'label_origin':'pixel_teacher_correction_from_learned_selfplay','death_window':dead,'privileged_game_state_used':False,'policy_contract':'pixel-policy-contract-v1.1'})
            eps.append({'episode_id':eid,'duration_sec':round(time.time()-t0,3),'death_detected':dead,'action_counts':dict(acts),'candidate_disagreements':len(pending),'corrections_saved':len(kept)})
    with (root/'stage12_corrections.jsonl').open('w') as f:
        for r in records:f.write(json.dumps(r,sort_keys=True)+'\n')
    deaths=sum(e.get('death_detected',False) for e in eps);counts=Counter(r['action'] for r in records);accepted=len(records)>=10 and len({r['episode_id'] for r in records})>=2
    summary={'stage':'12-selfplay-failure-buffer-v1','episodes':eps,'death_count':deaths,'correction_examples':len(records),'correction_counts':dict(counts),'distinct_correction_episodes':len({r['episode_id'] for r in records}),'privileged_game_state_used':False,'accepted':accepted};(root/'stage12_buffer_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2));raise SystemExit(0 if accepted else 31)
if __name__=='__main__':main()
