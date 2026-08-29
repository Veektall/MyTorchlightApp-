#!/usr/bin/env python3
import argparse, csv, json, math, random
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from stage10_temporal_model import load_clip, Stage10Policy, ACTIONS, ACTION_TO_ID
from stage10_episode_split import load_or_create


class Clips(Dataset):
    def __init__(self, root, rows): self.root = Path(root); self.rows = rows
    def __len__(self): return len(self.rows)
    def __getitem__(self, i):
        r = self.rows[i]
        return load_clip(self.root / r['context_clip_path']), ACTION_TO_ID[r['action']], i


def metrics(y, p):
    cm = np.zeros((len(ACTIONS), len(ACTIONS)), dtype=int)
    for a, b in zip(y, p): cm[a, b] += 1
    recalls = []
    for i in range(len(ACTIONS)):
        d = cm[i].sum(); recalls.append(cm[i, i] / d if d else float('nan'))
    acc = float((np.array(y) == np.array(p)).mean()) if y else 0.0
    bal = float(np.nanmean(recalls))
    return acc, bal, cm, recalls


def evaluate(model, loader, device, rows):
    model.eval(); ys, ps, output = [], [], []
    with torch.no_grad():
        for x, y, idx in loader:
            probs = model(x.to(device)).softmax(1).cpu(); pred = probs.argmax(1)
            ys += y.tolist(); ps += pred.tolist()
            for j in range(len(y)):
                r = rows[int(idx[j])]; k = int(pred[j])
                output.append((r['example_id'], r['episode_id'], ACTIONS[int(y[j])], ACTIONS[k], float(probs[j, k])))
    return ys, ps, output


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', required=True); ap.add_argument('--epochs', type=int, default=48); args = ap.parse_args()
    root = Path(args.root); random.seed(53); np.random.seed(53); torch.manual_seed(53)
    rows = [json.loads(x) for x in (root/'stage9_actions.jsonl').read_text().splitlines() if x.strip()]
    train, val, split = load_or_create(root, rows)
    counts = {a: sum(r['action'] == a for r in train) for a in ACTIONS}
    if any(counts[a] == 0 for a in ACTIONS): raise SystemExit('training split lost an action class')
    weights = [1.0 / counts[r['action']] for r in train]
    sampler = WeightedRandomSampler(weights, num_samples=max(len(train), 240), replacement=True)
    tl = DataLoader(Clips(root, train), batch_size=16, sampler=sampler, num_workers=0)
    vl = DataLoader(Clips(root, val), batch_size=16, shuffle=False, num_workers=0)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = Stage10Policy().to(device)
    ck = torch.load(root/'stage10_temporal_encoder.pt', map_location='cpu'); model.encoder.load_state_dict(ck['encoder'])
    opt = torch.optim.AdamW(model.parameters(), lr=7e-4, weight_decay=2e-4)
    hist = []
    for _ in range(args.epochs):
        model.train(); losses = []
        for x, y, _ in tl:
            x = x.to(device); y = y.to(device); logits = model(x)
            loss = F.cross_entropy(logits, y, label_smoothing=.03)
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0); opt.step(); losses.append(loss.item())
        hist.append(float(np.mean(losses)))
    y, p, pred_rows = evaluate(model, vl, device, val)
    acc, bal, cm, recalls = metrics(y, p)
    val_counts = {a: sum(r['action'] == a for r in val) for a in ACTIONS}
    majority_id = max(range(len(ACTIONS)), key=lambda i: val_counts[ACTIONS[i]])
    majority_acc = sum(int(v == majority_id) for v in y) / max(1, len(y))
    constant_balanced_accuracy = 1.0 / len(ACTIONS)
    always_jump_acc = sum(int(v == ACTION_TO_ID['jump']) for v in y) / max(1, len(y))
    recall_map = {ACTIONS[i]: (None if math.isnan(recalls[i]) else float(recalls[i])) for i in range(len(ACTIONS))}
    maneuver_ok = all(recall_map[a] is not None and recall_map[a] >= .25 for a in ['left','right','jump','roll'])
    stay_ok = recall_map['stay'] is not None and recall_map['stay'] >= .20
    accepted = acc > majority_acc and bal >= .35 and maneuver_ok and stay_ok
    torch.save({'model': model.state_dict(), 'actions': ACTIONS, 'input_size': [8,3,54,96], 'stage10_temporal_init': True, 'seed': 53, 'policy_contract': 'pixel-policy-contract-v1.1'}, root/'stage10_imitation_policy.pt')
    with (root/'stage10_predictions.csv').open('w', newline='') as f:
        w = csv.writer(f); w.writerow(['example_id','episode_id','true_action','pred_action','pred_confidence']); w.writerows(pred_rows)
    summary = {
        'stage': '10-balanced-imitation-policy-v2', 'examples_total': len(rows), 'train_examples': len(train), 'validation_examples': len(val),
        'validation_split': split, 'train_counts': counts, 'validation_counts': val_counts, 'epochs': args.epochs, 'device': device,
        'initialized_from_stage10_temporal_encoder': True, 'balanced_sampling': True,
        'validation_accuracy': round(acc, 4), 'validation_balanced_accuracy': round(bal, 4),
        'baselines': {'majority_accuracy': round(majority_acc, 4), 'always_jump_accuracy': round(always_jump_acc, 4), 'constant_policy_balanced_accuracy': round(constant_balanced_accuracy, 4)},
        'per_class_recall': {k: (None if v is None else round(v, 4)) for k,v in recall_map.items()}, 'confusion_matrix': cm.tolist(),
        'acceptance_gate': {'accuracy_must_exceed_majority': True, 'balanced_accuracy_min': .35, 'maneuver_recall_min': .25, 'stay_recall_min': .20},
        'privileged_game_state_used': False, 'accepted': accepted,
        'interpretation': 'Accepted only if held-out whole-episode performance beats cheap baselines and every maneuver has meaningful recall.'
    }
    (root/'stage10_policy_summary.json').write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2))
    if not accepted: raise SystemExit(14)

if __name__ == '__main__': main()
