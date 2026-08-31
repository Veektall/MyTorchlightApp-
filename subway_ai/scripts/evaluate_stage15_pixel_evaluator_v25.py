#!/usr/bin/env python3
"""Stage 15 v25: robust rendered-prompt sensing without weakening acceptance.

v24 established the correct single trusted actuator path, but its broad Tesseract crop recognized
rendered tutorial prompts far too late (Down visible ~150s, recognized ~223s; Left visible ~300s,
recognized ~577s).  v25 keeps the v23 causal screenshot-generation guard and v24 single-click
actuator, but alternates a tight thresholded prompt reader with the old broad reader.  Each prompt
sample performs exactly one OCR call.  The initial tutorial runtime budget is extended so runtime
limits cannot masquerade as tutorial failure; the strict score/prompt/motion handoff is unchanged.
"""

import json
import re
import sys
from pathlib import Path

import evaluate_stage15_pixel_evaluator_v24 as v24

v23 = v24.v23
v20 = v24.v20
v17 = v24.v17
s = v24.s

# Preserve the broad v17 reader as a fallback cadence.  v17.prompt_job is already v23's wrapper,
# which records capture-generation/timestamp metadata for causal lateral-action gating.
_broad_prompt_reader = v23._orig_prompt_job
_prompt_sensor_stats = {
    'tight_calls': 0,
    'broad_calls': 0,
    'tight_hits': 0,
    'broad_hits': 0,
}
_prompt_call_index = 0


def _direction_from_text(text):
    n = ' '.join(re.sub(r'[^a-z]+', ' ', (text or '').lower()).split())
    instruction = any(x in n for x in ('press', 'arrow', 'key', 'swipe'))
    if not instruction:
        return None
    if 'left' in n:
        return 'left'
    if 'right' in n:
        return 'right'
    if 'down' in n or 'roll' in n:
        return 'down'
    if 'up' in n or 'jump' in n:
        return 'up'
    if 'space' in n or 'hoverboard' in n:
        return 'space'
    return None


def _tight_prompt_reader(im):
    """Read only the rendered center instruction band, tuned from v24 gameplay pixels."""
    from PIL import Image, ImageOps

    w, h = im.size
    # Recorded v24 prompts consistently occupy this center-lower band.  The crop excludes HUD,
    # page chrome, and most background text, reducing false positives and OCR latency.
    roi = im.crop((int(w * .28), int(h * .48), int(w * .72), int(h * .68)))
    g = ImageOps.grayscale(roi).resize((roi.width * 3, roi.height * 3), Image.Resampling.BICUBIC)
    g = ImageOps.autocontrast(g)
    bw = g.point(lambda x: 255 if x > 170 else 0)
    try:
        text = s.pytesseract.image_to_string(bw, config='--psm 11', lang='eng').lower()
    except Exception:
        return None, ''
    return _direction_from_text(text), text[-260:]


def hybrid_prompt_reader(im):
    """One OCR call per sample: tight reader twice, broad reader every third sample."""
    global _prompt_call_index
    _prompt_call_index += 1
    if _prompt_call_index % 3:
        _prompt_sensor_stats['tight_calls'] += 1
        d, txt = _tight_prompt_reader(im)
        if d:
            _prompt_sensor_stats['tight_hits'] += 1
        return d, txt
    _prompt_sensor_stats['broad_calls'] += 1
    d, txt = _broad_prompt_reader(im)
    if d:
        _prompt_sensor_stats['broad_hits'] += 1
    return d, txt


# v23.prompt_job_v23 calls v23._orig_prompt_job dynamically and then records causal capture
# metadata.  Swap only that underlying rendered-prompt reader; preserve the causal wrapper.
v23._orig_prompt_job = hybrid_prompt_reader

# v17.main passes 600s for the one-time tutorial bootstrap.  That limit cut v24 off only 23s after
# Left was finally recognized.  Extend runtime headroom without changing any acceptance threshold.
_bootstrap_v24 = v17.bootstrap


def bootstrap_v25(canvas, tracker, tutorial_required, max_sec):
    budget = max(float(max_sec), 1200.0) if tutorial_required else float(max_sec)
    result = _bootstrap_v24(canvas, tracker, tutorial_required, budget)
    result['requested_bootstrap_budget_sec'] = float(max_sec)
    result['effective_bootstrap_budget_sec'] = budget
    return result


v17.bootstrap = bootstrap_v25


def _stamp_v25(out_path):
    if not out_path:
        return
    p = Path(out_path) / 'stage15_summary.json'
    if not p.exists():
        return
    q = json.loads(p.read_text())
    q['stage'] = '15-pixel-evaluator-repair-v25'
    q['tutorial_prompt_sensor'] = {
        'mode': 'hybrid_tight_threshold_2of3_plus_broad_1of3',
        'source': 'rendered_canvas_pixels_only',
        'tight_roi_xyxy_fraction': [.28, .48, .72, .68],
        'tight_threshold': 170,
        'tight_psm': 11,
        'stats': dict(_prompt_sensor_stats),
    }
    q['tutorial_bootstrap_runtime_budget_sec'] = 1200.0
    q['acceptance_thresholds_unchanged_from_v24'] = True
    p.write_text(json.dumps(q, indent=2))


def main():
    out = None
    try:
        out = sys.argv[sys.argv.index('--out') + 1]
    except Exception:
        pass
    code = 0
    try:
        v24.main()
    except SystemExit as e:
        code = int(e.code or 0)
    _stamp_v25(out)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
