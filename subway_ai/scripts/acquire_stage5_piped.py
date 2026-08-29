#!/usr/bin/env python3
import argparse,json,re,subprocess,urllib.request,urllib.parse
from pathlib import Path

PIPED=[
 'https://pipedapi.kavin.rocks','https://pipedapi.leptons.xyz','https://pipedapi.nosebs.ru',
 'https://piped-api.privacy.com.de','https://pipedapi.adminforge.de','https://pipedapi.drgns.space',
 'https://pipedapi.owo.si','https://piped-api.codespace.cz','https://pipedapi.reallyaweso.me',
 'https://api.piped.private.coffee','https://pipedapi.darkness.services','https://pipedapi.orangenet.cc',
 'https://pipedapi.ducks.party'
]
INVIDIOUS=['https://inv.nadeko.net','https://invidious.nerdvpn.de','https://yt.chocolatemoo53.com']
HEADERS={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36','Accept':'application/json,text/plain,*/*','Accept-Language':'en-US,en;q=0.9'}

def get_json(url,timeout=15):
    req=urllib.request.Request(url,headers=HEADERS)
    with urllib.request.urlopen(req,timeout=timeout) as r:
        if r.status!=200: raise RuntimeError(f'HTTP {r.status}')
        return json.loads(r.read().decode())

def qnum(s):
    m=re.search(r'(\d+)',str(s or '')); return int(m.group(1)) if m else 0

def try_piped(video_id,errors):
    for base in PIPED:
        try:
            d=get_json(f'{base}/streams/{video_id}')
            streams=d.get('videoStreams') or []
            if not streams: raise RuntimeError('no videoStreams')
            return {'kind':'piped','base':base,'data':d,'streams':streams,'title':d.get('title') or '', 'uploader':d.get('uploader')}
        except Exception as e: errors.append(f'Piped {base}: {type(e).__name__}: {e}')

def try_invidious(video_id,errors):
    for base in INVIDIOUS:
        try:
            d=get_json(f'{base}/api/v1/videos/{video_id}?local=true')
            streams=[]
            for s in (d.get('adaptiveFormats') or [])+(d.get('formatStreams') or []):
                typ=str(s.get('type') or s.get('mimeType') or '')
                if 'video/' not in typ and not s.get('qualityLabel'): continue
                streams.append({'url':s.get('url'),'quality':s.get('qualityLabel') or s.get('quality'),'format':typ,'codec':typ,'mimeType':typ,'bitrate':s.get('bitrate',0),'videoOnly':not bool(s.get('audioQuality'))})
            if not streams: raise RuntimeError('no usable video formats')
            return {'kind':'invidious','base':base,'data':d,'streams':streams,'title':d.get('title') or '', 'uploader':d.get('author')}
        except Exception as e: errors.append(f'Invidious {base}: {type(e).__name__}: {e}')

def download(url,out):
    cmd=['curl','--fail','--location','--retry','3','--retry-delay','1','--retry-all-errors','--connect-timeout','15','--max-time','300','-A',HEADERS['User-Agent'],'-H','Accept: */*',url,'-o',str(out)]
    return subprocess.run(cmd).returncode==0 and out.exists() and out.stat().st_size>100000

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--video-id',required=True); ap.add_argument('--out',required=True); ap.add_argument('--expected-title',default=''); a=ap.parse_args()
    errors=[]; source=try_piped(a.video_id,errors) or try_invidious(a.video_id,errors)
    if not source:
        print(json.dumps({'ok':False,'errors':errors},indent=2)); raise SystemExit(2)
    title=str(source['title'])
    if a.expected_title and a.expected_title.lower() not in title.lower():
        raise SystemExit(f'title mismatch: {title!r}')
    streams=source['streams']
    good=[s for s in streams if s.get('url') and 480<=qnum(s.get('quality'))<=1080]
    if not good: good=[s for s in streams if s.get('url')]
    def score(s):
        fmt=(str(s.get('format') or '')+' '+str(s.get('codec') or '')+' '+str(s.get('mimeType') or '')).lower()
        h264=1 if ('h264' in fmt or 'avc' in fmt or 'mp4' in fmt) else 0
        return (h264,qnum(s.get('quality')),int(s.get('bitrate') or 0))
    ranked=sorted(good,key=score,reverse=True)
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    chosen=None
    for s in ranked[:8]:
        try:
            if download(s['url'],out):
                probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=width,height,avg_frame_rate,codec_name','-of','json',str(out)],capture_output=True,text=True)
                if probe.returncode==0 and 'streams' in probe.stdout:
                    chosen=s; break
        except Exception as e: errors.append(f"stream {s.get('quality')}: {type(e).__name__}: {e}")
        out.unlink(missing_ok=True)
    if not chosen:
        print(json.dumps({'ok':False,'source':source['base'],'errors':errors},indent=2)); raise SystemExit(3)
    probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size:stream=width,height,avg_frame_rate,codec_name','-of','json',str(out)],capture_output=True,text=True,check=True)
    meta={'ok':True,'video_id':a.video_id,'title':title,'uploader':source['uploader'],'transport_kind':source['kind'],'instance':source['base'],'selected_stream':{k:chosen.get(k) for k in ['quality','format','codec','mimeType','bitrate','videoOnly']},'ffprobe':json.loads(probe.stdout),'errors_before_success':errors}
    Path(str(out)+'.transport.json').write_text(json.dumps(meta,indent=2)); print(json.dumps(meta,indent=2))
if __name__=='__main__': main()
