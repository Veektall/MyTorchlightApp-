#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from zipvoice.tokenizer.tokenizer import EmiliaTokenizer
from zipvoice.utils.feature import VocosFbank


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--audio', required=True)
    p.add_argument('--transcript', required=True)
    p.add_argument('--model-dir', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--duration', type=float, default=10.0)
    p.add_argument('--target-rms', type=float, default=0.01)
    a=p.parse_args()
    model_dir=Path(a.model_dir)
    out=Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav=Path(td)/'reference-24k.wav'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-i',a.audio,'-t',str(a.duration),'-ac','1','-ar','24000',str(wav)], check=True)
        audio,_=sf.read(wav,dtype='float32',always_2d=False)
    audio=np.asarray(audio,dtype=np.float32).squeeze()
    if not audio.size:
        raise SystemExit('Reference audio is empty')
    tensor=torch.from_numpy(audio).unsqueeze(0)
    rms=torch.sqrt(torch.mean(tensor**2)).item()
    tensor=tensor*(a.target_rms/max(rms,1e-8))
    feature_extractor=VocosFbank()
    prompt_features=feature_extractor.extract(tensor,sampling_rate=24000).cpu().unsqueeze(0)*0.1
    prompt_features_lens=torch.tensor([prompt_features.size(1)],dtype=torch.int64)
    tokenizer=EmiliaTokenizer(token_file=str(model_dir/'tokens.txt'))
    prompt_tokens=tokenizer.texts_to_token_ids([a.transcript])
    torch.save({
        'prompt_tokens':prompt_tokens,
        'prompt_features_lens':prompt_features_lens,
        'prompt_features':prompt_features,
        'prompt_rms':torch.tensor(a.target_rms,dtype=torch.float32),
        'transcript':a.transcript,
        'duration_seconds':a.duration,
        'source_audio':Path(a.audio).name,
    },out)
    print(f'Wrote prompt: {out} ({prompt_features.shape})')
if __name__=='__main__': main()
