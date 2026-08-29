#!/usr/bin/env python3
from pathlib import Path
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

ACTIONS = ['stay', 'left', 'right', 'jump', 'roll']
ACTION_TO_ID = {a:i for i,a in enumerate(ACTIONS)}


def load_clip(path, frames=8, width=96, height=54):
    cap = cv2.VideoCapture(str(path)); xs = []
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        xs.append(cv2.resize(rgb, (width, height), interpolation=cv2.INTER_AREA))
    cap.release()
    if not xs:
        raise RuntimeError(f'No frames in {path}')
    ids = np.linspace(0, len(xs) - 1, frames).round().astype(int)
    arr = np.stack([xs[i] for i in ids]).astype(np.float32) / 255.0
    return torch.from_numpy(arr).permute(0, 3, 1, 2).contiguous()


class FrameEncoder(nn.Module):
    def __init__(self, dim=64):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(3, 16, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d(1))
        self.proj = nn.Linear(64, dim)
    def forward(self, x):
        return self.proj(self.net(x).flatten(1))


class TemporalEncoder(nn.Module):
    def __init__(self, frame_dim=64, hidden=96):
        super().__init__()
        self.frame = FrameEncoder(frame_dim)
        self.gru = nn.GRU(frame_dim, hidden, batch_first=True)
    def forward(self, x):
        b, t, c, h, w = x.shape
        z = self.frame(x.reshape(b*t, c, h, w)).reshape(b, t, -1)
        seq, hid = self.gru(z)
        return seq, hid[-1]


class Stage10Pretrainer(nn.Module):
    """Predict frame 8 as persistence plus a learned temporal residual from frames 1..7."""
    def __init__(self, frame_dim=64, hidden=96, temperature=0.10):
        super().__init__()
        self.encoder = TemporalEncoder(frame_dim, hidden)
        self.future_delta = nn.Sequential(
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, frame_dim))
        # Start exactly at the persistence baseline: delta = 0.
        nn.init.zeros_(self.future_delta[-1].weight)
        nn.init.zeros_(self.future_delta[-1].bias)
        self.direction = nn.Linear(hidden, 2)
        self.temperature = temperature

    def forward(self, x):
        _, h = self.encoder(x[:, :7])
        last = self.encoder.frame(x[:, 6])
        pred = F.normalize(last + self.future_delta(h), dim=1)
        # Stop-gradient target prevents the target representation from moving merely to
        # make the prediction task easier; learning pressure stays on history + residual.
        target = F.normalize(self.encoder.frame(x[:, 7]), dim=1).detach()
        return pred, target, self.direction(h)

    def contrastive_loss(self, pred, target):
        logits = pred @ target.t() / self.temperature
        labels = torch.arange(len(pred), device=pred.device)
        return 0.5 * (F.cross_entropy(logits, labels) + F.cross_entropy(logits.t(), labels))


class Stage10Policy(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = TemporalEncoder()
        self.head = nn.Sequential(nn.Linear(96,64),nn.ReLU(),nn.Dropout(.15),nn.Linear(64,len(ACTIONS)))
    def forward(self,x):
        _,h=self.encoder(x)
        return self.head(h)
