#!/usr/bin/env python3
import argparse, json, subprocess
from collections import Counter
from pathlib import Path
from prepare_video_corpus import detect_crop

ACTIONS = ['stay', 'left', 'right', 'jump', 'roll']
MIN_EPISODES = 6
MIN_PER_CLASS = 30
MIN_EPISODE_COVERAGE = 4
# collect_stage9_balanced.js intentionally warms ffmpeg for 700 ms before the action clock starts.
VIDEO_LEAD_SEC = 0.700
# End clips conservatively before the logged keydown to make post-action leakage impossible despite recorder-start jitter.
PRE_ACTION_GUARD_SEC = 0.100


def probe_video(path):
    cmd = ['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,duration','-of','json',str(path)]
    data = json.loads(subprocess.check_output(cmd, text=True))['streams'][0]
    num, den = data['r_frame_rate'].split('/')
    fps = float(num) / float(den)
    return {'width': int(data['width']), 'height': int(data['height']), 'fps': fps, 'duration_sec': float(data.get('duration') or 0)}


def select_decisions(decisions):
    selected, last = [], {}
    for d in decisions:
        action = d['action']; t = float(d['t_sec'])
        min_gap = 0.48 if action != 'stay' else 0.90
        if t < 0.75 or t - last.get(action, -99) < min_gap:
            continue
        if action == 'stay' and any(abs(float(x['t_sec']) - t) < 0.42 and x['action'] != 'stay' for x in decisions):
            continue
        last[action] = t
        selected.append(d)
    return selected


def emit_clip(video, out_path, action_t, crop):
    end = VIDEO_LEAD_SEC + action_t - PRE_ACTION_GUARD_SEC
    start = max(0.0, end - 8/15)
    if end - start < 0.45:
        return False
    filters = []
    if crop:
        filters.append(f'crop={crop}')
    filters += ['fps=15','scale=640:360:force_original_aspect_ratio=decrease','pad=640:360:(ow-iw)/2:(oh-ih)/2:black']
    cmd = ['ffmpeg','-y','-v','error','-ss',f'{start:.4f}','-i',str(video),'-t',f'{end-start:.4f}','-an','-vf',','.join(filters),'-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p',str(out_path)]
    subprocess.run(cmd, check=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--episodes', required=True)
    args = ap.parse_args()
    root = Path(args.root); root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(Path(args.episodes).read_text())
    episodes = [e for e in payload['episodes'] if e.get('accepted')]
    out = root / 'stage9_exact_examples'; out.mkdir(parents=True, exist_ok=True)

    records, episode_reports = [], []
    for ep in episodes:
        video = Path(ep['video_path']); actions_path = Path(ep['actions_path'])
        if not video.exists() or not actions_path.exists():
            episode_reports.append({'episode_id': ep['episode_id'], 'accepted': False, 'reason': 'missing_video_or_action_log'})
            continue
        meta = probe_video(video)
        quality_ok = meta['width'] == 1280 and meta['height'] == 720 and 28.0 <= meta['fps'] <= 31.0 and meta['duration_sec'] >= 23.0
        crop, crop_method = detect_crop(video)
        decisions = json.loads(actions_path.read_text())['decisions']
        selected = select_decisions(decisions)
        counts = Counter(d['action'] for d in selected)
        episode_reports.append({'episode_id': ep['episode_id'], 'accepted': quality_ok, 'video': meta, 'active_gameplay_crop': crop, 'crop_method': crop_method, 'selected_action_counts': dict(counts)})
        if not quality_ok:
            continue
        for d in selected:
            idx = len(records) + 1
            clip = out / f"{idx:05d}-{ep['episode_id']}-{d['action']}.mp4"
            if not emit_clip(video, clip, float(d['t_sec']), crop):
                continue
            records.append({
                'example_id': idx,
                'episode_id': ep['episode_id'],
                'source_id': ep['episode_id'],
                'action_time_sec': round(float(d['t_sec']), 4),
                'video_action_time_sec_estimate': round(VIDEO_LEAD_SEC + float(d['t_sec']), 4),
                'clip_end_before_action_sec': PRE_ACTION_GUARD_SEC,
                'action': d['action'],
                'confidence': 1.0,
                'label_origin': 'exact_browser_input',
                'eligible_for_training': True,
                'dataset_role': 'targeted_exact_action_calibration',
                'context_clip_path': str(clip.relative_to(root)),
                'input_frames': 8,
                'input_fps': 15,
                'input_ends_at_or_before_action_onset': True,
                'privileged_game_state_used': False,
                'policy_contract': 'pixel-policy-contract-v1.1',
                'provenance': 'self_generated_official_game_episode',
                'active_gameplay_crop': crop,
                'crop_method': crop_method
            })

    with (root/'stage9_actions.jsonl').open('w') as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + '\n')

    counts = Counter(r['action'] for r in records)
    episode_coverage = {a: len({r['episode_id'] for r in records if r['action'] == a}) for a in ACTIONS}
    usable_episodes = sorted({r['episode_id'] for r in records})
    accepted = (
        len(usable_episodes) >= MIN_EPISODES and
        all(counts[a] >= MIN_PER_CLASS for a in ACTIONS) and
        all(episode_coverage[a] >= MIN_EPISODE_COVERAGE for a in ACTIONS)
    )
    summary = {
        'stage': '9-targeted-balanced-exact-dataset-v1',
        'policy_contract': 'pixel-policy-contract-v1.1',
        'examples_total': len(records),
        'usable_episodes': usable_episodes,
        'usable_episode_count': len(usable_episodes),
        'counts': {a: counts[a] for a in ACTIONS},
        'episode_coverage_by_action': episode_coverage,
        'canonical_observation': 'temporally active gameplay crop -> 640x360 landscape at 15 fps',
        'input_frames': 8,
        'post_action_pixels_in_examples': False,
        'alignment': {
            'recorder_lead_sec': VIDEO_LEAD_SEC,
            'pre_action_guard_sec': PRE_ACTION_GUARD_SEC,
            'reason': 'Conservative guard keeps all extracted frames before exact browser keydown despite recorder-start jitter.'
        },
        'acceptance_contract': {
            'minimum_usable_episodes': MIN_EPISODES,
            'minimum_examples_per_class': MIN_PER_CLASS,
            'minimum_distinct_episodes_per_action': MIN_EPISODE_COVERAGE,
            'validation_must_hold_out_whole_episodes': True
        },
        'accepted': accepted,
        'episode_reports': episode_reports
    }
    (root/'stage9_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if not accepted:
        raise SystemExit(12)

if __name__ == '__main__':
    main()
