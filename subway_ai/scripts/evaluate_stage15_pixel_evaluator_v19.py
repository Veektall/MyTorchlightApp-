#!/usr/bin/env python3
import json
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import evaluate_stage15_pixel_evaluator_v17 as v17


def bootstrap_v19(canvas, tracker, tutorial_required, max_sec):
    """Pixel-only tutorial bootstrap with persistent prompt intent and motion-gated actuation.

    OCR identifies the rendered tutorial direction but is a noisy/asynchronous sensor.  Once a
    direction is recognized it remains armed through OCR misses until the trusted keypress causes
    visible motion to resume.  After motion resumes the direction is remembered but disarmed, so a
    later checkpoint requires a fresh rendered-prompt recognition before another action.  This
    prevents both v16's drop-on-OCR-miss failure and v17/v18's stale-direction spam while moving.
    """
    t0 = time.time()
    prev = None
    motions = deque(maxlen=24)
    short_motion = deque(maxlen=8)
    scores = deque(maxlen=120)

    last_score = None
    last_change = -99.0
    last_score_submit = -99.0
    score_future = None
    reset_candidates = deque(maxlen=4)

    prompt_future = None
    prompt_frame_t = None
    last_prompt_submit = -99.0
    pending = None
    armed = False
    armed_score = None
    last_prompt_confirmed = -99.0
    last_prompt_text = ''
    last_press = -99.0
    last_motion_resume = -99.0
    last_resume_event = -99.0

    death_future = None
    death_frame_t = None
    last_death_submit = -99.0
    death_text = ''

    last_recover = -99.0
    last_safe_jump = -99.0
    events = []
    seen = []
    valid_reads = 0
    max_ever = 0

    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='stage15-pixel-v19')
    try:
        while time.time() - t0 < max_sec:
            now = time.time() - t0
            png = canvas.screenshot()
            im = v17.s.pil_from_png(png)
            rgb, gray = v17.s.decode_png(png)
            if prev is not None:
                m = v17.s.mean_abs(gray, prev)
                motions.append(m)
                short_motion.append(m)
            prev = gray

            motion_med = float(np.median(short_motion)) if short_motion else 1.0
            frozen = len(short_motion) >= 6 and motion_med < .0030
            moving = len(short_motion) >= 6 and motion_med > .0080

            # Score OCR: monotonic continuity is authoritative.  A possible reset must be confirmed
            # by several consecutive low readings; one low hallucination (v18 saw 000158 -> 5) can
            # never reset the tracker.
            if score_future is not None and score_future.done():
                try:
                    v = score_future.result()
                except Exception:
                    v = None
                score_future = None
                if v is not None:
                    valid_reads += 1
                    v = int(v)
                    if last_score is None:
                        last_score = v
                        last_change = now
                        reset_candidates.clear()
                    elif v >= last_score and v <= last_score + 250:
                        if v > last_score:
                            last_change = now
                        last_score = v
                        reset_candidates.clear()
                    elif last_score >= 35 and v <= 30 and v < last_score * .35:
                        if reset_candidates and (now - reset_candidates[-1][0] > 2.2 or v + 3 < reset_candidates[-1][1]):
                            reset_candidates.clear()
                        reset_candidates.append((now, v))
                        if len(reset_candidates) >= 3 and reset_candidates[-1][0] - reset_candidates[0][0] <= 4.5:
                            first = reset_candidates[0][1]
                            vals = [x[1] for x in reset_candidates]
                            if first <= 15 and all(b + 3 >= a for a, b in zip(vals, vals[1:])):
                                last_score = vals[-1]
                                last_change = now
                                events.append({'t': round(now, 2), 'event': 'score_reset_confirmed', 'score': last_score, 'reads': vals})
                                reset_candidates.clear()
                    else:
                        reset_candidates.clear()
                    if last_score is not None:
                        max_ever = max(max_ever, int(last_score))
                        scores.append((now, int(last_score)))
            if score_future is None and now - last_score_submit >= .7:
                score_future = pool.submit(v17.score_job, im.copy())
                last_score_submit = now

            # Consume asynchronous prompt OCR.  Results from frames captured before a visible
            # post-action motion resume are stale and must not re-arm an already-cleared prompt.
            if prompt_future is not None and prompt_future.done():
                try:
                    d, txt = prompt_future.result()
                except Exception:
                    d, txt = None, ''
                captured_t = prompt_frame_t
                prompt_future = None
                prompt_frame_t = None
                last_prompt_text = txt
                if d:
                    if captured_t is not None and captured_t + .15 < last_motion_resume:
                        events.append({'t': round(now, 2), 'event': 'stale_prompt_result_discarded', 'direction': d, 'captured_t': round(captured_t, 2)})
                    else:
                        if d != pending:
                            pending = d
                            if not seen or seen[-1] != d:
                                seen.append(d)
                        armed = True
                        armed_score = last_score
                        last_prompt_confirmed = now
                        events.append({'t': round(now, 2), 'event': 'prompt_armed', 'direction': d, 'score': last_score, 'text': txt[-120:]})

            stalled = last_score is not None and now - last_change >= 1.6
            if prompt_future is None and now - last_prompt_submit >= .9 and (tutorial_required or stalled or pending is not None):
                prompt_frame_t = now
                prompt_future = pool.submit(v17.prompt_job, im.copy())
                last_prompt_submit = now

            # Positive causal transition: a trusted prompt action followed by rendered motion.
            # Disarm immediately but remember the direction.  This is the crucial separation that
            # lets repeated Left checkpoints be handled without continuously steering Left between them.
            if armed and last_press > -90 and moving and now - last_press <= 3.0:
                armed = False
                last_motion_resume = now
                if now - last_resume_event > .8:
                    events.append({'t': round(now, 2), 'event': 'prompt_action_motion_resumed', 'direction': pending, 'score': last_score, 'motion': round(motion_med, 6)})
                    last_resume_event = now

            if armed and pending:
                # OCR may miss after the first recognition, but the direction remains authoritative
                # while the rendered scene is frozen.  Repeated presses stop as soon as pixels move.
                fresh_recognition = now - last_prompt_confirmed <= 1.4
                if (frozen or fresh_recognition) and now - last_press >= .48:
                    canvas.press(v17.PROMPT_KEY[pending], delay=180)
                    last_press = now
                    events.append({'t': round(now, 2), 'event': 'prompt_press_motion_gated', 'direction': pending, 'score': last_score, 'frozen': bool(frozen), 'motion': round(motion_med, 6)})

            # Strong death/collision evidence is allowed to recover the environment, but recovery
            # never erases pending tutorial intent.  No generic recovery is allowed merely because
            # prompt OCR is absent.
            color_death = bool(v17.s.legacy_death(rgb))
            if frozen and stalled and death_future is None and now - last_death_submit >= 2.4:
                death_frame_t = now
                death_future = pool.submit(v17.death_text_job, im.copy())
                last_death_submit = now
            if death_future is not None and death_future.done():
                try:
                    death_text = death_future.result() or ''
                except Exception:
                    death_text = ''
                death_future = None
                death_frame_t = None
            death_kw = next((w for w in v17.s.DEATH_WORDS if w in death_text), None)

            if pending is not None:
                if (death_kw or color_death) and stalled and now - last_recover >= 2.0:
                    key = 'Enter' if int(now / 2.0) % 2 == 0 else 'Space'
                    canvas.press(key, delay=180)
                    last_recover = now
                    armed = False
                    events.append({'t': round(now, 2), 'event': 'visual_collision_recovery', 'key': key, 'pending_direction': pending, 'score': last_score, 'evidence': ('text:' + death_kw) if death_kw else 'legacy_color'})
            else:
                # Before any tutorial direction is known, bootstrap the page/start screen exactly as
                # previous successful versions did.  Between known directions, ordinary motion is left
                # alone; ArrowUp is only a keep-alive while score is actively advancing.
                if last_score is not None and now - last_change < 1.8 and now - last_safe_jump >= .95:
                    canvas.press('ArrowUp', delay=180)
                    last_safe_jump = now
                if (last_score is None or now - last_change >= 6.0) and now - last_recover >= 1.8:
                    key = ['Enter', 'Space', 'ArrowUp'][int(now / 1.8) % 3]
                    canvas.press(key, delay=180)
                    last_recover = now
                    events.append({'t': round(now, 2), 'event': 'bootstrap_recovery_press', 'key': key, 'score': last_score})

            # Genuine handoff requires prompt-free, continuously advancing rendered gameplay.  A
            # remembered (disarmed) direction is not itself a blocker; recent rendered prompt evidence is.
            if last_score is not None and len(scores) >= 5:
                med = float(np.median(motions)) if motions else 0.0
                recent = [(t, val) for t, val in scores if now - t <= 9.0]
                growth = (last_score - min(val for _, val in recent)) if len(recent) >= 4 else 0
                advancing = now - last_change < 1.5
                threshold = 220 if tutorial_required else 18
                prompt_quiet = now - last_prompt_confirmed >= 7.0 and not armed
                if max_ever >= threshold and growth >= 12 and advancing and med > .0025 and prompt_quiet:
                    v17.v15.v13.v12.v11.v10.v9.arm_tracker(tracker, last_score)
                    return {
                        'ok': True,
                        'tutorial_completed': bool(tutorial_required),
                        'startup_controller': 'persistent_motion_gated_prompt_v19',
                        'tutorial_prompt_sequence': seen,
                        'tutorial_events': events[-360:],
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
        'reason': 'persistent_motion_gated_bootstrap_timeout_v19',
        'startup_controller': 'persistent_motion_gated_prompt_v19',
        'tutorial_prompt_sequence': seen,
        'tutorial_events': events[-440:],
        'last_prompt_text': last_prompt_text,
        'pending_direction': pending,
        'prompt_armed': bool(armed),
        'last_score': last_score,
        'max_bootstrap_score': max_ever,
        'valid_score_reads': valid_reads,
        'motion_median': round(float(np.median(motions)), 6) if motions else 0.0,
    }


v17.bootstrap = bootstrap_v19


def main():
    code = 0
    try:
        v17.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    # v17 owns the benchmark loop; stamp the durable summary with the actual evaluator version.
    try:
        i = sys.argv.index('--out')
        p = Path(sys.argv[i + 1]) / 'stage15_summary.json'
        if p.exists():
            s = json.loads(p.read_text())
            s['stage'] = '15-pixel-evaluator-repair-v19'
            p.write_text(json.dumps(s, indent=2))
    except Exception:
        pass
    raise SystemExit(code)


if __name__ == '__main__':
    main()
