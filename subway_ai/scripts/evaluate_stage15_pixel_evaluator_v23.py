#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path

import numpy as np
import evaluate_stage15_pixel_evaluator_v20 as v20

v17 = v20.v17
s = v17.s

# v22 proved that wall-clock OCR completion time is not causal evidence that a prompt frame was
# captured after the previous lane change. Tesseract may finish an older screenshot later. Attach
# a lateral-action generation and capture timestamp to every PIL frame, then allow a second Left /
# Right only when OCR confirms the direction from a frame captured in the CURRENT generation.
_capture = {'generation': 0}
_orig_pil_from_png = s.pil_from_png

def pil_from_png_v23(png):
    im = _orig_pil_from_png(png)
    try:
        im.info['stage15_lateral_generation'] = int(_capture['generation'])
        im.info['stage15_capture_mono'] = float(time.monotonic())
    except Exception:
        pass
    return im

s.pil_from_png = pil_from_png_v23

_orig_prompt_job = v17.prompt_job
_prompt_state = {
    'direction': None,
    'confirmed_mono': -99.0,
    'capture_mono': -99.0,
    'capture_generation': -1,
    'misses': 99,
}

def prompt_job_v23(im):
    cap_gen = int(im.info.get('stage15_lateral_generation', -1))
    cap_mono = float(im.info.get('stage15_capture_mono', -99.0))
    d, txt = _orig_prompt_job(im)
    if d:
        _prompt_state['direction'] = d
        _prompt_state['confirmed_mono'] = time.monotonic()
        _prompt_state['capture_mono'] = cap_mono
        _prompt_state['capture_generation'] = cap_gen
        _prompt_state['misses'] = 0
    else:
        _prompt_state['misses'] += 1
        if _prompt_state['misses'] >= 2:
            _prompt_state['direction'] = None
    return d, txt

v17.prompt_job = prompt_job_v23

_KEY_DIR = {'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left', 'ArrowRight': 'right'}
_last_lateral_action = {'ArrowLeft': -99.0, 'ArrowRight': -99.0}
_guard_stats = {
    'vertical_allowed': 0,
    'lateral_allowed': 0,
    'lateral_suppressed': 0,
    'stale_generation_suppressed': 0,
    'other_allowed': 0,
}

def trusted_press_v23(canvas, key):
    d = _KEY_DIR.get(key)
    now = time.monotonic()
    if d in ('left', 'right'):
        same_direction = _prompt_state['direction'] == d
        current_generation = _prompt_state['capture_generation'] == _capture['generation']
        fresh_completion = now - _prompt_state['confirmed_mono'] <= 1.70
        captured_after_last_action = _prompt_state['capture_mono'] >= _last_lateral_action[key] + 1.35
        if not current_generation:
            _guard_stats['stale_generation_suppressed'] += 1
        if not (same_direction and current_generation and fresh_completion and captured_after_last_action):
            _guard_stats['lateral_suppressed'] += 1
            return False

    # Canonical actuator contract: focus/click the rendered game canvas then a real locator keypress.
    s.focus_canvas(canvas)
    canvas.press(key, delay=180)

    if d in ('left', 'right'):
        _last_lateral_action[key] = now
        # Any OCR result from a screenshot captured before this point is now causally stale.
        _capture['generation'] += 1
        _guard_stats['lateral_allowed'] += 1
    elif d in ('up', 'down'):
        _guard_stats['vertical_allowed'] += 1
    else:
        _guard_stats['other_allowed'] += 1
    return True

v20.trusted_press = trusted_press_v23

# Benchmark policy actions keep the same independently verified focus/click + 180 ms actuator.
_orig_policy_episode = v17.run_policy_episode
class TrustedCanvasProxy:
    def __init__(self, canvas):
        self._canvas = canvas
    def __getattr__(self, name):
        return getattr(self._canvas, name)
    def press(self, key, delay=180, **kwargs):
        s.focus_canvas(self._canvas)
        return self._canvas.press(key, delay=180, **kwargs)

def run_policy_episode_v23(canvas, *args, **kwargs):
    return _orig_policy_episode(TrustedCanvasProxy(canvas), *args, **kwargs)

v17.run_policy_episode = run_policy_episode_v23


def harden_summary(out_path, learned_episodes):
    p = Path(out_path) / 'stage15_summary.json'
    if not p.exists():
        return False
    q = json.loads(p.read_text())
    rr = q.get('results', [])
    by = {x: [r for r in rr if r.get('policy') == x and r.get('valid')]
          for x in ['stay', 'always_jump', 'corridor_cv', 'learned']}
    required = (len(by['stay']) == 1 and len(by['always_jump']) == 1 and
                len(by['corridor_cv']) == 1 and len(by['learned']) == learned_episodes)
    all_valid = bool(required and all(r.get('score_metric_available') and r.get('death_detected')
                                      for rs in by.values() for r in rs))
    med = {k: (float(np.median([r['max_pixel_score'] for r in rs])) if rs else None)
           for k, rs in by.items()}
    vals = [x for x in med.values() if x is not None]
    discriminative = bool(all_valid and len(vals) == 4 and
                          (max(vals) - min(vals) >= 5 or max(vals) >= 1.05 * max(1.0, min(vals))))
    lm = med['learned']
    cheap = [med['stay'], med['always_jump']]
    beats = bool(all_valid and lm is not None and all(x is not None and lm > x for x in cheap))
    competence = bool(beats and med['corridor_cv'] is not None and lm >= .8 * med['corridor_cv'])
    best = max(by['learned'], key=lambda r: r['max_pixel_score']) if by['learned'] else None
    q.update({
        'stage': '15-pixel-evaluator-repair-v23',
        'normal_endless_play_verified': all_valid,
        'pixel_score_metric_available': all_valid,
        'run_to_verified_death': all_valid,
        'evaluator_discriminative': discriminative,
        'benchmark_complete': all_valid,
        'learned_beats_both_cheap_baselines': beats,
        'competence_claim': competence,
        'highest_learned_score': best['max_pixel_score'] if best else None,
        'highest_score_video': best.get('video_file') if best else None,
        'completed': bool(all_valid and discriminative),
        'completion_contract': 'all_6_runs_pixel_score_plus_visual_death_and_discriminative_scores',
        'tutorial_actuator_guard': {
            'mode': 'capture_generation_causal_lateral_guard',
            'final_capture_generation': int(_capture['generation']),
            'guard_stats': dict(_guard_stats),
        },
    })
    p.write_text(json.dumps(q, indent=2))
    return bool(q['completed'])


def main():
    out = None
    learned = 3
    try:
        out = sys.argv[sys.argv.index('--out') + 1]
    except Exception:
        pass
    try:
        learned = int(sys.argv[sys.argv.index('--learned-episodes') + 1])
    except Exception:
        pass
    code = 0
    try:
        v17.main()
    except SystemExit as e:
        code = int(e.code or 0)
    done = harden_summary(out, learned) if out else False
    raise SystemExit(0 if done else (code or 61))

if __name__ == '__main__':
    main()
