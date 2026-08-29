#!/usr/bin/env python3
import argparse,json,re,subprocess,sys,urllib.request
from pathlib import Path

INSTANCES=[
 'https://pipedapi.kavin.rocks',
 'https://pipedapi.adminforge.de',
 'https://api.piped.private.coffee',
 'https://pipedapi.leptons.xyz',
 'https://api.piped.yt',
]

def get_json(url,timeout=20):
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 Stage5Research/1.0','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        if r.status!=200: raise RuntimeError(f'HTTP {r.status}')
        return json.loads(r.read().decode())

def qnum(s):
    m=re.search(r'(\d+)',str(s or '')); return int(m.group(1)) if m else 0

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--video-id',required=True); ap.add_argument('--out',required=True); ap.add_argument('--expected-title',default=''); a=ap.parse_args()
    errors=[]; data=None; used=None
    for base in INSTANCES:
        try:
            d=get_json(f'{base}/streams/{a.video_id}')
            if not d.get('videoStreams'): raise RuntimeError('no videoStreams')
            data=d; used=base; break
        except Exception as e: errors.append(f'{base}: {type(e).__name__}: {e}')
    if not data:
        print(json.dumps({'ok':False,'errors':errors},indent=2)); raise SystemExit(2)
    title=str(data.get('title') or '')
    if a.expected_title and a.expected_title.lower() not in title.lower():
        raise SystemExit(f'title mismatch: {title!r}')
    streams=data['videoStreams']
    # Pixels only: audio is unnecessary. Prefer H.264/MP4 up to 1080p, then any useful video stream.
    good=[s for s in streams if s.get('url') and qnum(s.get('quality'))>=480 and qnum(s.get('quality'))<=1080]
    if not good: good=[s for s in streams if s.get('url')]
    def score(s):
        fmt=(str(s.get('format') or '')+' '+str(s.get('codec') or '')+' '+str(s.get('mimeType') or '')).lower()
        h264=1 if ('h264' in fmt or 'avc' in fmt or 'mp4' in fmt) else 0
        return (h264,qnum(s.get('quality')),int(s.get('bitrate') or 0))
    s=max(good,key=score)
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    cmd=['curl','--fail','--location','--retry','4','--retry-all-errors','--connect-timeout','20','--max-time','300','-A','Mozilla/5.0',s['url'],'-o',str(out)]
    subprocess.run(cmd,check=True)
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=width,height,avg_frame_rate,codec_name','-of','json',str(out)],capture_output=True,text=True,check=True)
    meta={'ok':True,'video_id':a.video_id,'title':title,'uploader':data.get('uploader'),'duration':data.get('duration'),'instance':used,'selected_stream':{k:s.get(k) for k in ['quality','format','codec','mimeType','bitrate','videoOnly']},'ffprobe':json.loads(probe.stdout),'errors_before_success':errors}
    Path(str(out)+'.transport.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta,indent=2))
if __name__=='__main__': main()
