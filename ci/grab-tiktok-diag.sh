#!/usr/bin/env bash
set -Eeuo pipefail
E=evidence; mkdir -p "$E"; PKG=com.veektall.grab; ACT=com.veektall.grab/.MainActivity; URL='https://vt.tiktok.com/ZS47aLxxn/'
adb install -r -t Grab.apk | tee "$E/install.txt"; grep -q Success "$E/install.txt"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb shell am force-stop "$PKG"; adb shell am start -W -n "$ACT" > "$E/start.txt"; sleep 2
adb shell uiautomator dump /sdcard/home.xml >/dev/null; adb pull /sdcard/home.xml "$E/home.xml" >/dev/null
python3 - "$E/home.xml" > "$E/ask.txt" <<'PY'
import re,sys,xml.etree.ElementTree as ET
for n in ET.parse(sys.argv[1]).getroot().iter('node'):
 t=n.attrib.get('text',''); d=n.attrib.get('content-desc','')
 if t.startswith('Ask') or d=='Default download quality':
  m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
  if m:
   a=list(map(int,m.groups())); print((a[0]+a[2])//2,(a[1]+a[3])//2); raise SystemExit
raise SystemExit('quality control absent')
PY
read X Y < "$E/ask.txt"; adb shell input tap "$X" "$Y"; sleep 1
adb shell uiautomator dump /sdcard/q.xml >/dev/null; adb pull /sdcard/q.xml "$E/q.xml" >/dev/null
python3 - "$E/q.xml" > "$E/hd.txt" <<'PY'
import re,sys,xml.etree.ElementTree as ET
r=ET.parse(sys.argv[1]).getroot(); texts=[n.attrib.get('text','') for n in r.iter('node')]
for x in ['Always ask','HD — higher quality','SD — data saver']:
 assert x in texts,x
for n in r.iter('node'):
 if n.attrib.get('text')=='HD — higher quality':
  m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds','')); a=list(map(int,m.groups())); print((a[0]+a[2])//2,(a[1]+a[3])//2); break
PY
read X Y < "$E/hd.txt"; adb shell input tap "$X" "$Y"; sleep 1
adb logcat -c
adb shell am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "$URL" -n "$ACT" | tee "$E/send.txt"
for i in $(seq 1 60); do sleep 3; adb logcat -d > "$E/logcat.txt"; grep -q 'GrabTikTok.*TIKTOK_COMPLETE' "$E/logcat.txt" && break; done
adb logcat -d > "$E/logcat.txt"; grep -E 'GrabResolve|GrabTikTok|GrabEngine|YoutubeDL|AndroidRuntime|FATAL EXCEPTION|yt-dlp|ERROR|Exception' "$E/logcat.txt" > "$E/focused.txt" || true
adb shell 'find /sdcard/Download/Grab -type f -printf "%p %s\n" 2>/dev/null' > "$E/files.txt" || true
if grep -q 'GrabTikTok.*TIKTOK_COMPLETE' "$E/logcat.txt"; then echo COMPLETE | tee "$E/verdict.txt"; exit 0; fi
if grep -q 'GrabTikTok.*TIKTOK_JOB' "$E/logcat.txt"; then echo STARTED_NOT_COMPLETE | tee "$E/verdict.txt"; exit 22; fi
echo SERVICE_NOT_STARTED | tee "$E/verdict.txt"; exit 23
