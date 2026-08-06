#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch
from torch.nn.utils import parametrize
from zipvoice.models.modules.solver import get_time_steps
from zipvoice.tokenizer.tokenizer import EmiliaTokenizer
from linacodec.vocoder.vocos import Vocos

class OnnxModel:
    def __init__(self,text_encoder_path,fm_decoder_path,threads=4):
        opts=ort.SessionOptions(); opts.inter_op_num_threads=threads; opts.intra_op_num_threads=threads
        self.text_encoder=ort.InferenceSession(str(text_encoder_path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.fm_decoder=ort.InferenceSession(str(fm_decoder_path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.feat_dim=int(self.fm_decoder.get_modelmeta().custom_metadata_map['feat_dim'])
    def run_text_encoder(self,tokens,prompt_tokens,prompt_features_len,speed):
        ins=self.text_encoder.get_inputs(); out=self.text_encoder.get_outputs()[0].name
        return torch.from_numpy(self.text_encoder.run([out],{ins[0].name:tokens.numpy(),ins[1].name:prompt_tokens.numpy(),ins[2].name:prompt_features_len.numpy(),ins[3].name:speed.numpy()})[0])
    def run_fm_decoder(self,t,x,text_condition,speech_condition,guidance_scale):
        ins=self.fm_decoder.get_inputs(); out=self.fm_decoder.get_outputs()[0].name
        return torch.from_numpy(self.fm_decoder.run([out],{ins[0].name:t.numpy(),ins[1].name:x.numpy(),ins[2].name:text_condition.numpy(),ins[3].name:speech_condition.numpy(),ins[4].name:guidance_scale.numpy()})[0])

def sample(model,tokens,prompt_tokens,prompt_features,speed=1.3,t_shift=.9,guidance_scale=3.0,num_step=4,seed=24680):
    torch.manual_seed(seed)
    tokens=torch.tensor(tokens,dtype=torch.int64); prompt_tokens=torch.tensor(prompt_tokens,dtype=torch.int64)
    plen=torch.tensor(prompt_features.size(1),dtype=torch.int64); speed_t=torch.tensor(speed,dtype=torch.float32)
    text_condition=model.run_text_encoder(tokens,prompt_tokens,plen,speed_t)
    batch,num_frames,_=text_condition.shape
    times=get_time_steps(t_start=0.0,t_end=1.0,num_step=num_step,t_shift=t_shift)
    x=torch.randn(batch,num_frames,model.feat_dim)
    speech_condition=torch.nn.functional.pad(prompt_features,(0,0,0,num_frames-prompt_features.shape[1]))
    gs=torch.tensor(guidance_scale,dtype=torch.float32)
    for step in range(num_step):
        t_cur=times[step]; t_next=times[step+1]
        v=model.run_fm_decoder(t_cur,x,text_condition,speech_condition,gs)
        x1=x+(1.0-t_cur)*v; x0=x-t_cur*v
        x=(1.0-t_next)*x0+t_next*x1 if step<num_step-1 else x1
    return x[:,plen.item():,:]

def split_text(text,max_chars=260):
    text=' '.join(text.split()); sentences=re.split(r'(?<=[.!?])\s+',text)
    chunks=[]; cur=''
    for s in sentences:
        if not s: continue
        if cur and len(cur)+1+len(s)>max_chars: chunks.append(cur); cur=s
        else: cur=(cur+' '+s).strip()
    if cur: chunks.append(cur)
    return chunks

def main():
    p=argparse.ArgumentParser(); p.add_argument('--text'); p.add_argument('--text-file'); p.add_argument('--prompt',required=True); p.add_argument('--model-dir',required=True); p.add_argument('--output',required=True); p.add_argument('--threads',type=int,default=4); p.add_argument('--seed',type=int,default=24680); p.add_argument('--speed',type=float,default=1.0); p.add_argument('--steps',type=int,default=4); p.add_argument('--guidance',type=float,default=3.0); p.add_argument('--pause-ms',type=int,default=140)
    a=p.parse_args(); text=a.text or (Path(a.text_file).read_text(encoding='utf-8') if a.text_file else '')
    if not text.strip(): raise SystemExit('Provide --text or --text-file')
    md=Path(a.model_dir); prompt=torch.load(a.prompt,map_location='cpu',weights_only=False)
    model=OnnxModel(md/'text_encoder_int8.onnx',md/'fm_decoder_int8.onnx',a.threads)
    tokenizer=EmiliaTokenizer(token_file=str(md/'tokens.txt'))
    vocos=Vocos.from_hparams(str(md/'vocoder/config.yaml')).eval()
    parametrize.remove_parametrizations(vocos.upsampler.upsample_layers[0],'weight')
    parametrize.remove_parametrizations(vocos.upsampler.upsample_layers[1],'weight')
    vocos.load_state_dict(torch.load(md/'vocoder/vocos.bin',map_location='cpu',weights_only=False))
    prompt_tokens=prompt['prompt_tokens']; prompt_features=prompt['prompt_features']; prompt_rms=float(prompt['prompt_rms'])
    outputs=[]; manifest=[]
    for i,chunk in enumerate(split_text(text),1):
        tokens=tokenizer.texts_to_token_ids([chunk])
        pred=sample(model,tokens,prompt_tokens,prompt_features,speed=a.speed*1.3,t_shift=.9,guidance_scale=a.guidance,num_step=a.steps,seed=a.seed+i)
        wav=vocos.decode(pred.permute(0,2,1)/0.1).squeeze().clamp(-1,1).detach().cpu().numpy().astype(np.float32)
        if prompt_rms<0.1: wav*=prompt_rms/0.1
        peak=np.max(np.abs(wav)) if wav.size else 0
        if peak>0: wav=np.clip(wav*(0.89/peak),-1,1)
        outputs.append(wav); manifest.append({'index':i,'text':chunk,'samples':int(len(wav))})
    pause=np.zeros(int(48000*a.pause_ms/1000),dtype=np.float32); pieces=[]
    for i,w in enumerate(outputs):
        pieces.append(w)
        if i<len(outputs)-1: pieces.append(pause)
    full=np.concatenate(pieces)
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); sf.write(out,full,48000,subtype='PCM_16')
    out.with_suffix('.json').write_text(json.dumps({'text':text,'chunks':manifest,'sample_rate':48000,'duration_seconds':round(len(full)/48000,3)},indent=2),encoding='utf-8')
    print(f'Wrote {out} ({len(full)/48000:.2f}s)')
if __name__=='__main__': main()
