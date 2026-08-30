#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

import numpy as np
import evaluate_stage15_pixel_evaluator_v20 as v20

v17=v20.v17
s=v17.s

# v20 proved persistent score-gating gets through Up/Down but can spam Left after the rendered
# instruction disappears. Keep v20's state machine and add a second, independent pixel/OCR guard:
# a directional key may physically reach the game only while the async rendered-prompt reader has
# recently confirmed that exact direction. Two consecutive OCR misses close the gate.
_orig_prompt_job=v17.prompt_job
_prompt_state={'direction':None,'confirmed_mono':-99.0,'misses':99}

def prompt_job_v21(im):
    d,txt=_orig_prompt_job(im)
    if d:
        _prompt_state['direction']=d
        _prompt_state['confirmed_mono']=time.monotonic()
        _prompt_state['misses']=0
    else:
        _prompt_state['misses']+=1
        if _prompt_state['misses']>=2:
            _prompt_state['direction']=None
    return d,txt

v17.prompt_job=prompt_job_v21

_KEY_DIR={'ArrowUp':'up','ArrowDown':'down','ArrowLeft':'left','ArrowRight':'right'}
_last_actual={}
_guard_stats={'allowed':0,'suppressed':0}

def trusted_press_v21(canvas,key):
    d=_KEY_DIR.get(key)
    if d is not None:
        now=time.monotonic()
        fresh=(_prompt_state['direction']==d and now-_prompt_state['confirmed_mono']<=1.65)
        cooldown=(now-_last_actual.get(key,-99.0)>=2.15)
        if not (fresh and cooldown):
            _guard_stats['suppressed']+=1
            return False
        _last_actual[key]=now
    # Preserve canonical actuator: focus/click #pixi-canvas, then locator.press(...,delay=180).
    s.focus_canvas(canvas)
    canvas.press(key,delay=180)
    _guard_stats['allowed']+=1
    return True

# v20.bootstrap resolves trusted_press in the v20 module globals at call time.
v20.trusted_press=trusted_press_v21

# Every evaluated policy action must use the same trusted actuator. A transparent proxy lets the
# already-tested v17 policy/death/score loop remain unchanged while hardening canvas.press.
_orig_policy_episode=v17.run_policy_episode
class TrustedCanvasProxy:
    def __init__(self,canvas): self._canvas=canvas
    def __getattr__(self,name): return getattr(self._canvas,name)
    def press(self,key,delay=180,**kwargs):
        s.focus_canvas(self._canvas)
        return self._canvas.press(key,delay=180,**kwargs)

def run_policy_episode_v21(canvas,*args,**kwargs):
    return _orig_policy_episode(TrustedCanvasProxy(canvas),*args,**kwargs)

v17.run_policy_episode=run_policy_episode_v21


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
      'stage':'15-pixel-evaluator-repair-v21',
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
      'tutorial_actuator_guard':{'mode':'recent_rendered_prompt_confirmation','guard_stats':dict(_guard_stats)},
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
