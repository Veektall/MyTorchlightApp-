#!/usr/bin/env python3
import json
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import evaluate_stage15_pixel_evaluator_v19 as v19

v17 = v19.v17


def trusted_press(canvas, key):
    # Preserve the independently verified actuator contract for tutorial/bootstrap control.
    v17.s.focus_canvas(canvas)
    canvas.press(key, delay=180)


def bootstrap_v20(canvas, tracker, tutorial_required, max_sec):
    """Pixel-only tutorial bootstrap using score-gated persistent prompt intent.

    Key idea: the tutorial world can animate while its instruction remains active, so frame motion
    cannot tell us a prompt cleared.  OCR identifies the rendered direction.  That direction is
    held across OCR misses and repeatedly actuated only while the rendered HUD score is stalled.
    Substantial pixel-score progress plus prompt silence makes the direction dormant (remembered
    but not acted on), preventing the previous direction from sabotaging the next checkpoint while
    asynchronous OCR catches up.  Fresh OCR always re-arms the same direction if retirement was
    premature.
    """
    t0 = time.time()
    prev = None
    motions = deque(maxlen=24)
    scores = deque(maxlen=160)

    last_score = None
    last_change = -99.0
    last_score_submit = -99.0
    score_future = None
    reset_candidates = deque(maxlen=4)

    prompt_future = None
    last_prompt_submit = -99.0
    last_prompt_confirmed = -99.0
    last_prompt_text = ''
    pending = None
    active = False
    phase_base_score = None
    phase_started = -99.0
    last_press = -99.0

    death_future = None
    last_death_submit = -99.0
    death_text = ''
    last_recover = -99.0
    last_boot_press = -99.0

    events = []
    seen = []
    valid_reads = 0
    max_ever = 0

    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='stage15-pixel-v20')
    try:
        while time.time() - t0 < max_sec:
            now = time.time() - t0
            png = canvas.screenshot()
            im = v17.s.pil_from_png(png)
            rgb, gray = v17.s.decode_png(png)
            if prev is not None:
                motions.append(v17.s.mean_abs(gray, prev))
            prev = gray

            # Rendered-score OCR with monotonic continuity.  A reset requires three coherent low
            # reads so a single 000158 -> 5 hallucination can never reset the bootstrap state.
            if score_future is not None and score_future.done():
                try:
                    val = score_future.result()
                except Exception:
                    val = None
                score_future = None
                if val is not None:
                    valid_reads += 1
                    val = int(val)
                    if last_score is None:
                        last_score = val
                        last_change = now
                        reset_candidates.clear()
                    elif val >= last_score and val <= last_score + 250:
                        if val > last_score:
                            last_change = now
                        last_score = val
                        reset_candidates.clear()
                    elif last_score >= 35 and val <= 30 and val < last_score * .35:
                        if reset_candidates and (now - reset_candidates[-1][0] > 2.2 or val + 3 < reset_candidates[-1][1]):
                            reset_candidates.clear()
                        reset_candidates.append((now, val))
                        if len(reset_candidates) >= 3 and reset_candidates[-1][0] - reset_candidates[0][0] <= 4.5:
                            vals = [x[1] for x in reset_candidates]
                            if vals[0] <= 15 and all(b + 3 >= a for a, b in zip(vals, vals[1:])):
                                last_score = vals[-1]
                                last_change = now
                                active = False
                                events.append({'t': round(now, 2), 'event': 'score_reset_confirmed', 'score': last_score, 'reads': vals})
                                reset_candidates.clear()
                    else:
                        reset_candidates.clear()
                    if last_score is not None:
                        max_ever = max(max_ever, int(last_score))
                        scores.append((now, int(last_score)))
            if score_future is None and now - last_score_submit >= .70:
                score_future = pool.submit(v17.score_job, im.copy())
                last_score_submit = now

            # Async rendered-prompt OCR.  OCR is a direction sensor, not a control clock.
            if prompt_future is not None and prompt_future.done():
                try:
                    d, txt = prompt_future.result()
                except Exception:
                    d, txt = None, ''
                prompt_future = None
                last_prompt_text = txt
                if d:
                    if d != pending:
                        pending = d
                        phase_base_score = last_score
                        phase_started = now
                        if not seen or seen[-1] != d:
                            seen.append(d)
                        events.append({'t': round(now, 2), 'event': 'prompt_direction_changed', 'direction': d, 'score': last_score, 'text': txt[-120:]})
                    elif not active:
                        # Same direction may represent another obstacle in the same tutorial phase.
                        phase_base_score = last_score
                        phase_started = now
                        events.append({'t': round(now, 2), 'event': 'prompt_rearmed', 'direction': d, 'score': last_score, 'text': txt[-120:]})
                    active = True
                    last_prompt_confirmed = now

            stalled_for = (now - last_change) if last_score is not None else 999.0
            if prompt_future is None and now - last_prompt_submit >= .85 and (tutorial_required or stalled_for >= 1.0 or pending is not None):
                prompt_future = pool.submit(v17.prompt_job, im.copy())
                last_prompt_submit = now

            # Repeated trusted actuation is driven by score stall, never by global frame motion.
            # Fresh OCR gets one immediate press; thereafter the same direction persists through
            # OCR misses only while the HUD score has stopped advancing.
            fresh_prompt = active and (now - last_prompt_confirmed <= 1.35)
            score_stalled = active and last_score is not None and stalled_for >= 1.05
            if active and pending and (fresh_prompt or score_stalled) and now - last_press >= .52:
                trusted_press(canvas, v17.PROMPT_KEY[pending])
                last_press = now
                events.append({'t': round(now, 2), 'event': 'prompt_press_score_gated', 'direction': pending, 'score': last_score, 'stalled_for': round(stalled_for, 2)})

            # A phase becomes dormant only after meaningful score progress and several seconds with
            # no rendered direction recognized.  Dormant means "remember, do not act"; a fresh OCR
            # hit can re-arm immediately.  This prevents stale Down from being fired at a new Left.
            if active and pending and phase_base_score is not None and last_score is not None:
                phase_growth = last_score - phase_base_score
                prompt_silent = now - last_prompt_confirmed >= 4.0
                recently_advancing = now - last_change < 1.8
                if phase_growth >= 20 and prompt_silent and recently_advancing:
                    active = False
                    events.append({'t': round(now, 2), 'event': 'prompt_dormant_after_progress', 'direction': pending, 'base_score': phase_base_score, 'score': last_score, 'growth': phase_growth})

            # Recovery requires positive visual death/collision evidence.  Mere OCR absence or score
            # stall is never enough to sweep arbitrary keys.  After a recovery, require fresh prompt
            # OCR before resuming the remembered direction.
            stalled = last_score is not None and stalled_for >= 4.5
            color_death = bool(v17.s.legacy_death(rgb))
            if stalled and death_future is None and now - last_death_submit >= 2.2:
                death_future = pool.submit(v17.death_text_job, im.copy())
                last_death_submit = now
            if death_future is not None and death_future.done():
                try:
                    death_text = death_future.result() or ''
                except Exception:
                    death_text = ''
                death_future = None
            death_kw = next((w for w in v17.s.DEATH_WORDS if w in death_text), None)
            if (death_kw or color_death) and stalled and now - last_recover >= 2.2:
                key = 'Enter' if int(now / 2.2) % 2 == 0 else 'Space'
                trusted_press(canvas, key)
                last_recover = now
                active = False
                events.append({'t': round(now, 2), 'event': 'visual_collision_recovery', 'key': key, 'pending_direction': pending, 'score': last_score, 'evidence': ('text:' + death_kw) if death_kw else 'legacy_color'})

            # Initial page/start bootstrap only, before any tutorial direction is known.  Once a
            # direction has been observed we never perform a blind action sweep.
            if pending is None and (last_score is None or (last_score <= 2 and stalled_for >= 2.5)) and now - last_boot_press >= 1.8:
                key = 'Enter' if int(now / 1.8) % 2 == 0 else 'Space'
                trusted_press(canvas, key)
                last_boot_press = now
                events.append({'t': round(now, 2), 'event': 'initial_bootstrap_press', 'key': key, 'score': last_score})

            # Strict endless-play handoff.  This gate is unchanged in spirit: substantial tutorial
            # escape, prompt quiet, active score growth, and rendered motion.  Bootstrap score is
            # discarded by arming the tracker at handoff; policy clock starts afterwards.
            if last_score is not None and len(scores) >= 5:
                med = float(np.median(motions)) if motions else 0.0
                recent = [(t, val) for t, val in scores if now - t <= 9.0]
                growth = (last_score - min(val for _, val in recent)) if len(recent) >= 4 else 0
                advancing = now - last_change < 1.5
                threshold = 220 if tutorial_required else 18
                prompt_quiet = now - last_prompt_confirmed >= 7.0 and not active
                if max_ever >= threshold and growth >= 12 and advancing and med > .0025 and prompt_quiet:
                    v17.v15.v13.v12.v11.v10.v9.arm_tracker(tracker, last_score)
                    return {
                        'ok': True,
                        'tutorial_completed': bool(tutorial_required),
                        'startup_controller': 'persistent_score_gated_prompt_v20',
                        'tutorial_prompt_sequence': seen,
                        'tutorial_events': events[-440:],
                        'score_at_handoff': int(last_score),
                        'max_bootstrap_score': int(max_ever),
                        'recent_score_growth': int(growth),
                        'motion_median': round(med, 6),
                        'valid_score_reads': valid_reads,
                        'policy_clock_reset_after_tutorial': True,
                        'score_hud_xy': [.9275, .0675],
                    }
            time.sleep(.035)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return {
        'ok': False,
        'reason': 'persistent_score_gated_bootstrap_timeout_v20',
        'startup_controller': 'persistent_score_gated_prompt_v20',
        'tutorial_prompt_sequence': seen,
        'tutorial_events': events[-520:],
        'last_prompt_text': last_prompt_text,
        'pending_direction': pending,
        'prompt_active': bool(active),
        'phase_base_score': phase_base_score,
        'last_score': last_score,
        'max_bootstrap_score': max_ever,
        'valid_score_reads': valid_reads,
        'motion_median': round(float(np.median(motions)), 6) if motions else 0.0,
    }


v17.bootstrap = bootstrap_v20


def main():
    code = 0
    try:
        v17.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    try:
        i = sys.argv.index('--out')
        p = Path(sys.argv[i + 1]) / 'stage15_summary.json'
        if p.exists():
            summary = json.loads(p.read_text())
            summary['stage'] = '15-pixel-evaluator-repair-v20'
            p.write_text(json.dumps(summary, indent=2))
    except Exception:
        pass
    raise SystemExit(code)


if __name__ == '__main__':
    main()
