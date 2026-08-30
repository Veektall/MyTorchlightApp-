#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

import numpy as np
import evaluate_stage15_pixel_evaluator_v20 as v20

v17=v20.v17
s=v17.s

# Evidence from v20/v21 is asymmetric:
# - Up/Down require persistent retries through intermittent OCR misses and are not lane-destructive.
# - Left/Right can sabotage a just-cleared tutorial checkpoint if a stale direction keeps firing.
# Therefore only lateral actions need a fresh rendered-prompt instance before another physical press.
_orig_prompt_job=v17.prompt_job
_prompt_state={'direction':None,'confirmed_mono':-99.0,'misses':99}

def prompt_job_v22(im):
    d,txt=_orig_prompt_job(im)
    now=time.monotonic()
    if d:
        _prompt_state['direction']=d
        _prompt_state['confirmed_mono']=now
        _prompt_state['misses']=0
    else:
        _prompt_state['misses']+=1
        if _prompt_state['misses']>=2:
            _prompt_state['direction']=None
    return d,txt

v17.prompt_job=prompt_job_v22

_KEY_DIR={'ArrowUp':'up','ArrowDown':'down','ArrowLeft':'left','ArrowRight':'right'}
_last_actual={'ArrowLeft':-99.0,'ArrowRight':-99.0}
_lateral_block_until={'ArrowLeft':-99.0,'ArrowRight':-99.0}
_guard_stats={'vertical_allowed':0,'lateral_allowed':0,'lateral_suppressed':0,'other_allowed':0}

def trusted_press_v22(canvas,key):
    d=_KEY_DIR.get(key)
    now=time.monotonic()
    if d in ('left','right'):
        last=_last_actual[key]
        fresh=(_prompt_state['direction']==d and now-_prompt_state['confirmed_mono']<=1.25)
        # After a lane change, ignore OCR work that may have been captured before the action.
        # A retry requires a genuinely later rendered-prompt observation after a refractory window.
        post_action_confirmation=(_prompt_state['confirmed_mono']>=last+1.50)
        refractory=(now>=_lateral_block_until[key])
        if not (fresh and post_action_confirmation and refractory):
            _guard_stats['lateral_suppressed']+=1
            return False
        _last_actual[key]=now
        _lateral_block_until[key]=now+2.80
    # Preserve the independently verified actuator for every physical input.
    s.focus_canvas(canvas)
    canvas.press(key,delay=180)
    if d in ('up','down'):
        _guard_stats['vertical_allowed']+=1
    elif d in ('left','right'):
        _guard_stats['lateral_allowed']+=1
    else:
        _guard_stats['other_allowed']+=1
    return True

# v20.bootstrap resolves this global when it is called.
v20.trusted_press=trusted_press_v22

# Benchmark actions also use the canonical focus/click + 180ms locator.press path.
_orig_policy_episode=v17.run_policy_episode
class TrustedCanvasProxy:
    def __init__(self,canvas): self._canvas=canvas
    def __getattr__(self,name): return getattr(self._canvas,name)
    def press(self,key,delay=180,**kwargs):
        s.focus_canvas(self._canvas)
        return self._canvas.press(key,delay=180,**kwargs)

def run_policy_episode_v22(canvas,*args,**kwargs):
    return _orig_policy_episode(TrustedCanvasProxy(canvas),*args,**kwargs)

v17.run_policy_episode=run_policy_episode_v22


def harden_summary(out_path,learned_episodes):
    p=Path(out_path)/'stage15_summary.json'
    if not p.exists(): return False
    q=json.loads(p.read_text()); rr=q.get('results',[])
    by={x:[r for r in rr if r.get('policy')==x and r.get('valid')] for x in ['stay','always_jump','corridor_cv','learned']}
    required=(len(by['stay'])==1 and len(by['always_jump'])==1 and len(by['corridor_cv'])==1 and len(by['learned'])==learned_episodes)
    all_valid=bool(required and all(r.get('score_metric_available') and r.get('death_detected') for rs in by.values() for r in rs))
    med={k:(float(np.median([r['max_pixel_score'] for r in rs])) if rs else None) for k,rs in by.items()}
    vals=[x for x in med.values() if x is not None]
    discriminative=bool(all_valid and len(vals)==4 and (max(vals)-min(vals)>=5 or max(vals)>=1.05*max(1.0,min(vals))))
    lm=med['learned']; cheap=[med['stay'],med['always_jump']]
    beats=bool(all_valid and lm is not None and all(x is not None and lm>x for x in cheap))
    competence=bool(beats and med['corridor_cv'] is not None and lm>=.8*med['corridor_cv'])
    best=max(by['learned'],key=lambda r:r['max_pixel_score']) if by['learned'] else None
    q.update({
      'stage':'15-pixel-evaluator-repair-v22',
      'normal_endless_play_verified':all_valid,
      'pixel_score_metric_available':all_valid,
      'run_to_verified_death':all_valid,
      'evaluator_discriminative':discriminative,
      'benchmark_complete':all_valid,
      'learned_beats_both_cheap_baselines':beats,
      'competence_claim':competence,
      'highest_learned_score':best['max_pixel_score'] if best else None,
      'highest_score_video':best.get('video_file') if best else None,
      'completed':bool(all_valid and discriminative),
      'completion_contract':'all_6_runs_pixel_score_plus_visual_death_and_discriminative_scores',
      'tutorial_actuator_guard':{'mode':'persistent_vertical_fresh_instance_lateral','guard_stats':dict(_guard_stats)},
    })
    p.write_text(json.dumps(q,indent=2))
    return bool(q['completed'])


def main():
    out=None; learned=3
    try: out=sys.argv[sys.argv.index('--out')+1]
    except Exception: pass
    try: learned=int(sys.argv[sys.argv.index('--learned-episodes')+1])
    except Exception: pass
    code=0
    try: v17.main()
    except SystemExit as e: code=int(e.code or 0)
    done=harden_summary(out,learned) if out else False
    raise SystemExit(0 if done else (code or 61))

if __name__=='__main__': main()
