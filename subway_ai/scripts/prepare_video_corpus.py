#!/usr/bin/env python3
import argparse, csv, hashlib, json, math, re, shutil, subprocess, sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def run(cmd, check=True, capture=True):
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr[-4000:] if p.stderr else ''}")
    return p


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ffprobe(path):
    p = run(['ffprobe','-v','error','-show_entries','format=duration:stream=width,height,avg_frame_rate','-of','json',str(path)])
    return json.loads(p.stdout)


def detect_crop(path):
    p = run(['ffmpeg','-hide_banner','-ss','5','-t','40','-i',str(path),
             '-vf','cropdetect=limit=24:round=2:reset=0','-f','null','-'], check=False)
    text = (p.stderr or '') + (p.stdout or '')
    crops = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', text)
    if not crops:
        return None
    crop = Counter(crops[-80:]).most_common(1)[0][0]
    return ':'.join(crop)


def find_precaptured(sid, raw_dir):
    candidates=[]
    for x in raw_dir.glob(f'{sid}.*'):
        if x.suffix.lower() in {'.mp4','.webm','.mkv','.mov'}:
            candidates.append(x)
    return sorted(candidates)[0] if candidates else None


def download_source(row, raw_dir, max_seconds):
    sid = row['source_id']
    existing=find_precaptured(sid,raw_dir)
    if existing:
        meta_path=Path(str(existing)+'.meta.json')
        info=json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return existing,info,'browser_capture'

    template = str(raw_dir / f'{sid}.%(ext)s')
    cmd = ['yt-dlp','--no-playlist','--no-progress','--write-info-json',
           '--merge-output-format','mp4','-f','best[height<=720]/best',
           '--download-sections',f'*0-{max_seconds}','-o',template,row['url']]
    p = run(cmd, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or 'yt-dlp failed')[-4000:])
    media = find_precaptured(sid,raw_dir)
    if not media:
        raise RuntimeError('yt-dlp completed but no media file was found')
    info_path = raw_dir / f'{sid}.info.json'
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return media, info, 'yt_dlp'


def normalize(raw, out_path, crop, max_seconds):
    filters = []
    if crop:
        filters.append(f'crop={crop}')
    filters += ['scale=360:640:force_original_aspect_ratio=decrease',
                'pad=360:640:(ow-iw)/2:(oh-ih)/2:black','fps=15']
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(raw),'-t',str(max_seconds),
         '-vf',','.join(filters),'-an','-c:v','libx264','-preset','veryfast','-crf','23',
         '-g','30','-keyint_min','30','-sc_threshold','0','-pix_fmt','yuv420p',str(out_path)])


def clip_qc(path):
    p = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vf','fps=3,scale=90:160',
                        '-pix_fmt','gray','-f','rawvideo','-'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return {'motion_score':0.0,'brightness':0.0,'accepted':False,'reason':'decode_failed'}
    frame_bytes = 90 * 160
    n = len(p.stdout) // frame_bytes
    if n < 2:
        return {'motion_score':0.0,'brightness':0.0,'accepted':False,'reason':'too_few_frames'}
    arr = np.frombuffer(p.stdout[:n*frame_bytes], dtype=np.uint8).reshape(n,160,90).astype(np.float32)
    motion = float(np.abs(np.diff(arr, axis=0)).mean())
    brightness = float(arr.mean())
    accepted = motion >= 2.0 and 12.0 <= brightness <= 243.0
    return {'motion_score':round(motion,4),'brightness':round(brightness,3),
            'accepted':bool(accepted),'reason':'motion_ok' if accepted else 'low_motion_or_extreme_brightness'}


def extract_thumb(clip, dest):
    run(['ffmpeg','-y','-v','error','-ss','2','-i',str(clip),'-frames:v','1',
         '-vf','scale=180:320:force_original_aspect_ratio=decrease,pad=180:320:(ow-iw)/2:(oh-ih)/2:black',str(dest)])


def make_contact_sheet(records, root, out_path):
    accepted = [r for r in records if r.get('accepted')]
    accepted.sort(key=lambda r: r.get('motion_score',0), reverse=True)
    chosen = accepted[:24]
    if not chosen:
        return
    thumbs = root / '_thumbs'; thumbs.mkdir(exist_ok=True)
    tiles=[]
    for i,r in enumerate(chosen):
        p=thumbs/f'{i:02d}.jpg'
        try:
            extract_thumb(root / r['clip_path'], p)
            im=Image.open(p).convert('RGB')
            canvas=Image.new('RGB',(180,348),'white'); canvas.paste(im,(0,0))
            d=ImageDraw.Draw(canvas)
            d.text((4,322),f"{r['source_id']} {r['start_sec']:.0f}s m={r['motion_score']:.1f}",fill='black')
            tiles.append(canvas)
        except Exception:
            pass
    if not tiles:
        return
    cols=6; rows=math.ceil(len(tiles)/cols)
    sheet=Image.new('RGB',(cols*180,rows*348),'white')
    for i,t in enumerate(tiles): sheet.paste(t,((i%cols)*180,(i//cols)*348))
    sheet.save(out_path,quality=90)
    shutil.rmtree(thumbs,ignore_errors=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifest',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--max-sources',type=int,default=2)
    ap.add_argument('--max-seconds',type=int,default=360)
    ap.add_argument('--clip-seconds',type=int,default=4)
    ap.add_argument('--stride-seconds',type=int,default=2)
    args=ap.parse_args()

    root=Path(args.out); raw_dir=root/'raw'; norm_dir=root/'normalized'; clips_dir=root/'clips'
    for d in [raw_dir,norm_dir,clips_dir]: d.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader(open(args.manifest,newline='')))
    approved=[r for r in rows if r.get('auto_ingest','').lower()=='yes'][:args.max_sources]
    records=[]; sources=[]; failures=[]

    for row in approved:
        sid=row['source_id']
        try:
            raw,info,acquisition=download_source(row,raw_dir,args.max_seconds)
            crop=detect_crop(raw)
            norm=norm_dir/f'{sid}.mp4'
            normalize(raw,norm,crop,args.max_seconds)
            meta=ffprobe(norm); duration=float(meta['format']['duration'])
            source_record={
                'source_id':sid,'url':row['url'],'category':row['category'],
                'reuse_status':row['reuse_status'],'title':info.get('title'),
                'uploader':info.get('uploader'),'acquisition':acquisition,
                'downloaded_duration_sec':round(duration,3),'crop':crop,
                'normalized_sha256':sha256(norm)
            }
            sources.append(source_record)
            sdir=clips_dir/sid; sdir.mkdir(parents=True,exist_ok=True)
            start=0.0; idx=0
            while start + args.clip_seconds <= duration + 0.05:
                clip=sdir/f'{idx:05d}.mp4'
                run(['ffmpeg','-y','-v','error','-ss',f'{start:.3f}','-i',str(norm),
                     '-t',str(args.clip_seconds),'-c','copy','-avoid_negative_ts','make_zero',str(clip)])
                qc=clip_qc(clip)
                records.append({'source_id':sid,'clip_path':str(clip.relative_to(root)),
                     'start_sec':round(start,3),'end_sec':round(start+args.clip_seconds,3),
                     'frames_nominal':args.clip_seconds*15,'width':360,'height':640,'fps':15,
                     'crop':crop,'reuse_status':row['reuse_status'],**qc})
                idx+=1; start+=args.stride_seconds
            for p in raw_dir.glob(f'{sid}.*'):
                p.unlink(missing_ok=True)
        except Exception as e:
            failures.append({'source_id':sid,'url':row['url'],'error':str(e)})

    with open(root/'index.jsonl','w') as f:
        for r in records: f.write(json.dumps(r,sort_keys=True)+'\n')
    summary={
        'contract_version':'pixel-policy-contract-v1',
        'canonical_video':{'width':360,'height':640,'fps':15,'clip_seconds':args.clip_seconds,'stride_seconds':args.stride_seconds,'audio':False},
        'sources_attempted':len(approved),'sources_completed':len(sources),
        'clips_total':len(records),'clips_accepted_motion_qc':sum(bool(r['accepted']) for r in records),
        'sources':sources,'failures':failures
    }
    (root/'summary.json').write_text(json.dumps(summary,indent=2))
    make_contact_sheet(records,root,root/'contact-sheet.jpg')
    shutil.rmtree(raw_dir,ignore_errors=True)
    print(json.dumps(summary,indent=2))
    if not sources or not records:
        sys.exit(2)

if __name__=='__main__':
    main()
