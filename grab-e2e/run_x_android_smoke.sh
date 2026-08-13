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

# MediaStore is the authoritative publish destination on Android 10+. Grab logs
# the returned content URI and the completed staged-file size after publish.
LINE="$(grep 'TIKTOK_COMPLETE' evidence/logcat.txt | tail -n1)"
URI="$(printf '%s\n' "$LINE" | sed -n 's/.* uri=\([^ ]*\) size=.*/\1/p')"
SIZE="$(printf '%s\n' "$LINE" | sed -n 's/.* size=\([0-9][0-9]*\).*/\1/p')"
printf 'COMPLETION=%s\nURI=%s\nSIZE=%s\n' "$LINE" "$URI" "$SIZE" | tee evidence/media-proof.txt
[ -n "$URI" ]
[ -n "$SIZE" ]
[ "$SIZE" -gt 100000 ]

# Confirm the returned MediaStore object still exists and is queryable.
adb shell content query --uri "$URI" > evidence/media-row.txt
cat evidence/media-row.txt
grep -Eq 'Row:|_id=' evidence/media-row.txt

# Resolution must have been performed by yt-dlp's Twitter extractor.
grep -E 'GrabResolve|GrabTikTok|GrabEngine|AndroidRuntime|FATAL EXCEPTION' evidence/logcat.txt > evidence/focused-log.txt || true
grep -Eqi 'GrabResolve.*extractor=twitter|extractor=twitter' evidence/logcat.txt
! grep -E 'FATAL EXCEPTION|AndroidRuntime.*com\.veektall\.grab' evidence/logcat.txt

echo X_TWITTER_REAL_DOWNLOAD_E2E_PASS | tee evidence/result.txt
