#!/usr/bin/env python3
import argparse,json,time
from collections import Counter,deque
from pathlib import Path
import numpy as np
from playwright.sync_api import sync_playwright

from evaluate_stage11_closed_loop import BROWSER_ARGS,KEYS,ACTIONS,LearnedPolicy,CorridorPolicy,open_game,harden_startup,decode_png,is_death

def save_rgb8(out,episode,seq,ring):
    p=out/'failure_examples'/f'{episode}-{seq:05d}.rgb8';p.parent.mkdir(parents=True,exist_ok=True);np.stack(ring).astype(np.uint8).tofile(p);return str(p.relative_to(out))

def run_episode(browser,index,checkpoint,out,max_sec):
    eid=f'stage12-selfplay-{index:02d}';context,page,canvas,webgl=open_game(browser,eid)
    saved=[];all_decisions=[];near=deque(maxlen=8)
    try:
        startup=harden_startup(canvas)
        if not startup.get('ok'):return {'episode_id':eid,'valid':False,'reason':'startup_failed'},[]
        learned=LearnedPolicy(checkpoint);teacher=CorridorPolicy();ring=deque(maxlen=8);prev=None;t0=time.time();last_dec=-99.;dead=False;seq=0
        while time.time()-t0<max_sec:
            rgb,gray=decode_png(canvas.screenshot());t=time.time()-t0
            if is_death(rgb):dead=True;break
            ring.append(rgb)
            if len(ring)==8 and t-last_dec>=.26:
                action,conf=learned.act(ring,t);teacher_action,_=teacher.act(gray,prev,t)
                meta={'episode_id':eid,'decision':seq,'t_sec':round(t,4),'policy_action':action,'policy_confidence':round(conf,4),'teacher_action':teacher_action,'teacher_disagrees':action!=teacher_action,'input_shape':[8,54,96,3],'post_action_pixels':False,'privileged_game_state_used':False}
                near.append((np.stack(ring).copy(),dict(meta)));all_decisions.append(meta)
                capture=(action!=teacher_action and conf<.78) or conf<.48
                if capture:
                    rel=save_rgb8(out,eid,seq,ring);r={**meta,'example_path':rel,'buffer_reason':'teacher_disagreement' if action!=teacher_action else 'low_confidence','eligible_for_retraining':True};saved.append(r)
                if action!='stay':canvas.press(KEYS[action],delay=180)
                last_dec=t;seq+=1
            prev=gray;time.sleep(.055)
        if dead:
            existing={r['decision'] for r in saved}
            for frames,meta in near:
                if meta['decision'] in existing:continue
                rel=out/'failure_examples'/f"{eid}-{meta['decision']:05d}-near-death.rgb8";rel.parent.mkdir(parents=True,exist_ok=True);frames.astype(np.uint8).tofile(rel)
                saved.append({**meta,'example_path':str(rel.relative_to(out)),'buffer_reason':'near_death','eligible_for_retraining':True})
        dur=time.time()-t0;cnt=Counter(d['policy_action'] for d in all_decisions);tcnt=Counter(d['teacher_action'] for d in all_decisions)
        ep={'episode_id':eid,'valid':True,'survival_sec':round(dur,3),'death_detected':dead,'censored_at_cap':not dead and dur>=max_sec-.5,'decisions':len(all_decisions),'saved_failure_examples':len(saved),'policy_action_counts':{a:cnt[a] for a in ACTIONS},'teacher_action_counts':{a:tcnt[a] for a in ACTIONS},'teacher_disagreements':sum(d['teacher_disagrees'] for d in all_decisions),'mean_policy_confidence':round(float(np.mean([d['policy_confidence'] for d in all_decisions])),4) if all_decisions else None,'webgl':webgl}
        return ep,saved
    finally:context.close()

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--checkpoint',required=True);ap.add_argument('--out',required=True);ap.add_argument('--episodes',type=int,default=3);ap.add_argument('--max-seconds',type=float,default=32);args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    episodes=[];buffer=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False,args=BROWSER_ARGS)
        try:
            for i in range(1,args.episodes+1):
                try:ep,rows=run_episode(browser,i,args.checkpoint,out,args.max_seconds)
                except Exception as e:ep,rows={'episode_id':f'stage12-selfplay-{i:02d}','valid':False,'reason':str(e)},[]
                episodes.append(ep);buffer.extend(rows);print(json.dumps(ep),flush=True)
        finally:browser.close()
    with (out/'stage12_failure_examples.jsonl').open('w') as f:
        for r in buffer:f.write(json.dumps(r,sort_keys=True)+'\n')
    reasons=Counter(r['buffer_reason'] for r in buffer);valid=sum(bool(e.get('valid')) for e in episodes)
    summary={'stage':'12-pixel-policy-failure-buffer-v1','policy_contract':'pixel-policy-contract-v1.1','official_game':'https://poki.com/en/g/subway-surfers','requested_episodes':args.episodes,'valid_episodes':valid,'episodes':episodes,'failure_examples_total':len(buffer),'failure_examples_by_reason':dict(reasons),'retraining_manifest':'stage12_failure_examples.jsonl','capture_rule':'low-confidence or pixel-teacher disagreement, plus final ~2 seconds before pixel-detected death','post_action_pixels_in_saved_examples':False,'privileged_game_state_used':False,'ready_for_next_training_cycle':valid>=2 and len(buffer)>0,'completed':valid>=2}
    (out/'stage12_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
    if valid<2:raise SystemExit(22)
if __name__=='__main__':main()
