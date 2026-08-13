#!/usr/bin/env bash
set -Eeuo pipefail
: "${X_TEST_URL:?X_TEST_URL is required}"
mkdir -p evidence

adb install --no-streaming /tmp/grab-x.apk | tee evidence/install.txt
grep -q Success evidence/install.txt
adb logcat -c
adb shell am force-stop com.veektall.grab
adb shell am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "$X_TEST_URL" -n com.veektall.grab/.MainActivity | tee evidence/start.txt

# Wait for yt-dlp resolution to finish and the Ask-mode quality sheet to open.
READY=0
for i in $(seq 1 75); do
  sleep 4
  adb shell uiautomator dump /sdcard/x-quality.xml >/dev/null 2>&1 || true
  adb shell cat /sdcard/x-quality.xml > evidence/quality-ui.xml || true
  adb logcat -d > evidence/logcat-resolve.txt
  if grep -Fq 'Choose quality' evidence/quality-ui.xml; then READY=1; break; fi
  if grep -E 'GrabResolve.*RESOLVE_FAILED|FATAL EXCEPTION|AndroidRuntime.*com\.veektall\.grab' evidence/logcat-resolve.txt; then
    echo X_RESOLUTION_FAILED
    exit 72
  fi
done
[ "$READY" = 1 ]

# Tap the HD/high-quality row using the current UI hierarchy rather than hard-coded coordinates.
python3 - evidence/quality-ui.xml > /tmp/x-hd-tap.txt <<'PY'
import re,sys,xml.etree.ElementTree as ET
root=ET.parse(sys.argv[1]).getroot()
preferred=('High quality','720p','HD')
for wanted in preferred:
    for n in root.iter('node'):
        text=n.attrib.get('text','')
        if text==wanted or (wanted=='720p' and text.endswith('p') and text!='360p'):
            m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
            if m:
                x1,y1,x2,y2=map(int,m.groups())
                print((x1+x2)//2,(y1+y2)//2)
                raise SystemExit
raise SystemExit('HD/high-quality row not found')
PY
read HX HY < /tmp/x-hd-tap.txt
adb shell input tap "$HX" "$HY"

# The patched Twitter path reuses Grab's proven progressive foreground yt-dlp service.
COMPLETE=0
for i in $(seq 1 120); do
  sleep 4
  adb logcat -d > evidence/logcat.txt
  if grep -q 'GrabTikTok.*TIKTOK_COMPLETE' evidence/logcat.txt || grep -q 'TIKTOK_COMPLETE' evidence/logcat.txt; then
    COMPLETE=1
    break
  fi
  if grep -E 'FATAL EXCEPTION|AndroidRuntime.*com\.veektall\.grab' evidence/logcat.txt; then
    echo X_RUNTIME_FATAL
    exit 73
  fi
done
[ "$COMPLETE" = 1 ]

# Prove that Android actually received a non-trivial media file, not merely a UI success state.
adb shell 'find /sdcard/Download/Grab -type f -printf "%p %s\n" 2>/dev/null' > evidence/download-files.txt || true
cat evidence/download-files.txt
python3 - evidence/download-files.txt <<'PY'
import sys
ok=False
for line in open(sys.argv[1],errors='ignore'):
    try:
        size=int(line.rsplit(' ',1)[1])
        if size>100000:
            ok=True
            break
    except Exception:
        pass
if not ok:
    raise SystemExit('No published X/Twitter video file >100KB')
PY

# Resolution must have been performed by yt-dlp's Twitter extractor.
grep -E 'GrabResolve|GrabTikTok|GrabEngine|AndroidRuntime|FATAL EXCEPTION' evidence/logcat.txt > evidence/focused-log.txt || true
grep -Eq 'GrabResolve.*extractor=Twitter|extractor=Twitter' evidence/logcat.txt
! grep -E 'FATAL EXCEPTION|AndroidRuntime.*com\.veektall\.grab' evidence/logcat.txt

echo X_TWITTER_REAL_DOWNLOAD_E2E_PASS | tee evidence/result.txt
