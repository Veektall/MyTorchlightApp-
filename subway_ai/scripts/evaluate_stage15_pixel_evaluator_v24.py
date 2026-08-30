#!/usr/bin/env python3
import json
import sys
from pathlib import Path

import numpy as np
import evaluate_stage15_pixel_evaluator_v23 as v23

v20 = v23.v20
v17 = v23.v17
s = v23.s

# ProvenTrustedCanvas.press() (installed by v15 and used by s.open_game) ALREADY performs:
#   canvas tabindex/focus -> one forced center click -> locator.press(key, delay>=180)
# v20-v23 redundantly called s.focus_canvas(canvas) before invoking that wrapper, producing two
# forced clicks per action. v24 restores the independently verified actuator literally: one call to
# ProvenTrustedCanvas.press(). The v23 capture-generation guard is otherwise unchanged.
_guard_stats = {
    'vertical_allowed': 0,
    'lateral_allowed': 0,
    'lateral_suppressed': 0,
    'stale_generation_suppressed': 0,
    'other_allowed': 0,
    'physical_press_calls': 0,
}

def trusted_press_v24(canvas, key):
    d = v23._KEY_DIR.get(key)
    now = v23.time.monotonic()
    if d in ('left', 'right'):
        same_direction = v23._prompt_state['direction'] == d
        current_generation = v23._prompt_state['capture_generation'] == v23._capture['generation']
        fresh_completion = now - v23._prompt_state['confirmed_mono'] <= 1.70
        captured_after_last_action = v23._prompt_state['capture_mono'] >= v23._last_lateral_action[key] + 1.35
        if not current_generation:
            _guard_stats['stale_generation_suppressed'] += 1
        if not (same_direction and current_generation and fresh_completion and captured_after_last_action):
            _guard_stats['lateral_suppressed'] += 1
            return False

    # EXACT trusted path: the wrapper itself performs the single focus/click + 180 ms keypress.
    canvas.press(key, delay=180)
    _guard_stats['physical_press_calls'] += 1

    if d in ('left', 'right'):
        v23._last_lateral_action[key] = now
        v23._capture['generation'] += 1
        _guard_stats['lateral_allowed'] += 1
    elif d in ('up', 'down'):
        _guard_stats['vertical_allowed'] += 1
    else:
        _guard_stats['other_allowed'] += 1
    return True

v20.trusted_press = trusted_press_v24

# The original policy episode already receives ProvenTrustedCanvas from s.open_game. Restoring it
# removes v21-v23's proxy-level extra focus/click while preserving exactly the same policy logic.
v17.run_policy_episode = v23._orig_policy_episode


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
        'stage': '15-pixel-evaluator-repair-v24',
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
            'actuator_mode': 'single_proven_trusted_canvas_press',
            'final_capture_generation': int(v23._capture['generation']),
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
