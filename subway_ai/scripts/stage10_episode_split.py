#!/usr/bin/env python3
import itertools, json, math
from collections import Counter
from pathlib import Path

ACTIONS = ['stay', 'left', 'right', 'jump', 'roll']


def _counts(rows):
    c = Counter(r['action'] for r in rows)
    return {a: c[a] for a in ACTIONS}


def choose_episode_split(rows, holdout_fraction=0.25):
    episodes = sorted({r['episode_id'] for r in rows})
    if len(episodes) < 4:
        raise RuntimeError('Need at least four episodes for episode-level holdout')
    k = max(2, int(round(len(episodes) * holdout_fraction)))
    k = min(k, len(episodes) - 2)
    total = Counter(r['action'] for r in rows)
    best = None
    for combo in itertools.combinations(episodes, k):
        val_ids = set(combo)
        train = [r for r in rows if r['episode_id'] not in val_ids]
        val = [r for r in rows if r['episode_id'] in val_ids]
        tc, vc = Counter(r['action'] for r in train), Counter(r['action'] for r in val)
        if any(tc[a] == 0 or vc[a] == 0 for a in ACTIONS):
            continue
        # Prefer validation episodes whose class proportions resemble the full corpus.
        score = 0.0
        for a in ACTIONS:
            p_all = total[a] / max(1, len(rows))
            p_val = vc[a] / max(1, len(val))
            score += abs(p_all - p_val)
        size_penalty = abs(len(val) / len(rows) - holdout_fraction)
        candidate = (score + size_penalty, tuple(combo), train, val)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        raise RuntimeError('No whole-episode split preserves all five action classes in both train and validation sets')
    _, combo, train, val = best
    return train, val, list(combo)


def load_or_create(root, rows):
    root = Path(root); path = root / 'stage10_episode_split.json'
    if path.exists():
        spec = json.loads(path.read_text())
        val_ids = set(spec['validation_episode_ids'])
        train = [r for r in rows if r['episode_id'] not in val_ids]
        val = [r for r in rows if r['episode_id'] in val_ids]
    else:
        train, val, holdout = choose_episode_split(rows)
        spec = {
            'strategy': 'whole_episode_holdout_v1',
            'validation_episode_ids': holdout,
            'train_episode_ids': sorted({r['episode_id'] for r in train}),
            'train_examples': len(train),
            'validation_examples': len(val),
            'train_counts': _counts(train),
            'validation_counts': _counts(val)
        }
        path.write_text(json.dumps(spec, indent=2))
    if not train or not val or any(sum(r['action'] == a for r in train) == 0 or sum(r['action'] == a for r in val) == 0 for a in ACTIONS):
        raise RuntimeError('Stored episode split is invalid for the current dataset')
    return train, val, spec
