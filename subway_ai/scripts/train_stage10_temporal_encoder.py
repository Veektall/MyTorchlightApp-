#!/usr/bin/env python3
import argparse, json, math, random
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from stage10_temporal_model import load_clip, Stage10Pretrainer
from stage10_episode_split import load_or_create


class Clips(Dataset):
    def __init__(self, root, rows): self.root = Path(root); self.rows = rows
    def __len__(self): return len(self.rows)
    def __getitem__(self, i): return load_clip(self.root / self.rows[i]['context_clip_path'])


def evaluate(model, loader, device):
    model.eval(); preds, targets, latent_persistence = [], [], []
    direction_correct = 0; direction_total = 0; pixel_persistence = []
    with torch.no_grad():
        for x in loader:
            x = x.to(device)
            p, t, logits = model(x)
            preds.append(p.cpu()); targets.append(t.cpu())
            # Explicit persistence baseline: use frame 7's visual latent as the prediction for frame 8.
            latent_persistence.append(F.normalize(model.encoder.frame(x[:, 6]), dim=1).cpu())
            rev = torch.flip(x, [1]); _, _, rev_logits = model(rev)
            direction_correct += int((logits.argmax(1) == 0).sum()) + int((rev_logits.argmax(1) == 1).sum())
            direction_total += 2 * len(x)
            y = .299*x[:,7,0:1] + .587*x[:,7,1:2] + .114*x[:,7,2:3]
            prev = .299*x[:,6,0:1] + .587*x[:,6,1:2] + .114*x[:,6,2:3]
            pixel_persistence.append(F.l1_loss(prev, y).item())
    p = F.normalize(torch.cat(preds), dim=1)
    t = F.normalize(torch.cat(targets), dim=1)
    lp = F.normalize(torch.cat(latent_persistence), dim=1)
    labels = torch.arange(len(p))
    retrieval = float(((p @ t.t()).argmax(1) == labels).float().mean())
    persistence_retrieval = float(((lp @ t.t()).argmax(1) == labels).float().mean())
    chance = 1.0 / max(1, len(p))
    return {
        'future_latent_top1_retrieval_accuracy': retrieval,
        'latent_persistence_top1_retrieval_accuracy': persistence_retrieval,
        'chance_retrieval_baseline': chance,
        'forward_reversed_accuracy': direction_correct / max(1, direction_total),
        'previous_frame_persistence_l1_diagnostic': float(np.mean(pixel_persistence))
    }


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', required=True); ap.add_argument('--epochs', type=int, default=32); args = ap.parse_args()
    root = Path(args.root); random.seed(41); np.random.seed(41); torch.manual_seed(41)
    rows = [json.loads(x) for x in (root/'stage9_actions.jsonl').read_text().splitlines() if x.strip()]
    train, val, split = load_or_create(root, rows)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = Stage10Pretrainer().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1.2e-3, weight_decay=1e-4)
    tl = DataLoader(Clips(root, train), batch_size=24, shuffle=True, num_workers=0, drop_last=False)
    vl = DataLoader(Clips(root, val), batch_size=24, shuffle=False, num_workers=0)
    history = []
    for _ in range(args.epochs):
        model.train(); losses = []
        for x in tl:
            x = x.to(device); rev = torch.flip(x, [1]); xx = torch.cat([x, rev], 0)
            labels = torch.cat([torch.zeros(len(x), dtype=torch.long), torch.ones(len(x), dtype=torch.long)]).to(device)
            pred, target, direction = model(xx)
            loss = model.contrastive_loss(pred, target) + .20 * F.cross_entropy(direction, labels)
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0); opt.step(); losses.append(loss.item())
        history.append(float(np.mean(losses)))
    metrics = evaluate(model, vl, device)
    # The learned temporal predictor must beat both chance and the true persistence baseline.
    # A one-percentage-point margin avoids declaring a statistical tie a win on this small holdout.
    retrieval_gate = max(
        3.0 * metrics['chance_retrieval_baseline'],
        metrics['latent_persistence_top1_retrieval_accuracy'] + 0.01,
    )
    accepted = (
        metrics['future_latent_top1_retrieval_accuracy'] >= retrieval_gate
        and metrics['forward_reversed_accuracy'] >= 0.70
    )
    torch.save({'encoder': model.encoder.state_dict(), 'input_size': [8,3,54,96], 'seed': 41, 'objective': 'future_latent_contrastive_plus_temporal_direction', 'policy_contract': 'pixel-policy-contract-v1.1'}, root/'stage10_temporal_encoder.pt')
    summary = {
        'stage': '10-temporal-pretraining-v3', 'examples_total': len(rows), 'train_examples': len(train), 'validation_examples': len(val),
        'validation_split': split, 'epochs': args.epochs, 'device': device, 'final_train_loss': round(history[-1], 6),
        'objective': ['predict 8th-frame visual latent from first 7 frames with symmetric contrastive loss', 'classify forward versus reversed temporal order'],
        'policy_labels_used': False, 'privileged_game_state_used': False,
        'validation': {k: round(v, 6) for k,v in metrics.items()},
        'acceptance_gate': {
            'future_latent_top1_retrieval_accuracy_min': round(retrieval_gate, 6),
            'forward_reversed_accuracy_min': 0.70,
            'must_beat_explicit_baselines': ['3x chance retrieval', 'frame-7 latent persistence by >=0.01 absolute']
        },
        'accepted': accepted
    }
    (root/'stage10_temporal_summary.json').write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2))
    if not accepted or not all(math.isfinite(v) for v in metrics.values()): raise SystemExit(13)

if __name__ == '__main__': main()
