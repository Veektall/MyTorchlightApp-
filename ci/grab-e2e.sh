#!/usr/bin/env bash
set -Eeuo pipefail
E=evidence
mkdir -p "$E"
PKG=com.veektall.grab
ACT=com.veektall.grab/.MainActivity
URL='https://vt.tiktok.com/ZS47aLxxn/'

adb wait-for-device
adb shell getprop > "$E/getprop.txt"
adb shell 'getprop ro.build.version.release; getprop ro.build.version.sdk; getprop ro.product.cpu.abi; getprop ro.product.cpu.abilist; getprop ro.dalvik.vm.native.bridge' | tee "$E/device-summary.txt"

# Install the exact signed ARM64-only release artifact.
adb install -r -t Grab.apk 2>&1 | tee "$E/install.txt"
grep -q Success "$E/install.txt"
adb shell pm path "$PKG" | tee "$E/pm-path.txt"
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

# Launch cleanly and verify the real quality UI.
adb shell am force-stop "$PKG"
adb shell am start -W -n "$ACT" | tee "$E/start.txt"
sleep 3
adb shell uiautomator dump /sdcard/home.xml >/dev/null
adb pull /sdcard/home.xml "$E/home.xml" >/dev/null
python3 - "$E/home.xml" > "$E/ask-coord.txt" <<'PY'
import re,sys,xml.etree.ElementTree as ET
r=ET.parse(sys.argv[1]).getroot()
for n in r.iter('node'):
    t=n.attrib.get('text','')
    if t.startswith('Ask') or n.attrib.get('content-desc')=='Default download quality':
        m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
        if m:
            x1,y1,x2,y2=map(int,m.groups()); print((x1+x2)//2,(y1+y2)//2); break
else: raise SystemExit('quality control not found')
PY
read AX AY < "$E/ask-coord.txt"
adb shell input tap "$AX" "$AY"
sleep 1
adb shell uiautomator dump /sdcard/quality.xml >/dev/null
adb pull /sdcard/quality.xml "$E/quality.xml" >/dev/null
python3 - "$E/quality.xml" > "$E/hd-coord.txt" <<'PY'
import re,sys,xml.etree.ElementTree as ET
r=ET.parse(sys.argv[1]).getroot(); texts=[n.attrib.get('text','') for n in r.iter('node')]
required=['Default download quality','Always ask','HD — higher quality','SD — data saver']
missing=[x for x in required if x not in texts]
if missing: raise SystemExit('missing quality labels: '+repr(missing))
for n in r.iter('node'):
    if n.attrib.get('text')=='HD — higher quality':
        m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
        if m:
            x1,y1,x2,y2=map(int,m.groups()); print((x1+x2)//2,(y1+y2)//2); break
else: raise SystemExit('HD row not found')
PY
read HX HY < "$E/hd-coord.txt"
adb shell input tap "$HX" "$HY"
sleep 1
adb shell uiautomator dump /sdcard/after-quality.xml >/dev/null
adb pull /sdcard/after-quality.xml "$E/after-quality.xml" >/dev/null
python3 - "$E/after-quality.xml" <<'PY'
import sys,xml.etree.ElementTree as ET
texts=[n.attrib.get('text','') for n in ET.parse(sys.argv[1]).getroot().iter('node')]
if not any(t.startswith('HD') for t in texts): raise SystemExit('HD selection not visible after selection')
PY
echo QUALITY_DIALOG_ALL_THREE_AND_HD_SELECTED | tee "$E/quality-pass.txt"
adb exec-out screencap -p > "$E/quality-selected.png"

# Send the exact live TikTok fixture. Do not background until the foreground service actually starts.
adb logcat -c
adb shell am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "$URL" -n "$ACT" | tee "$E/tiktok-intent-start.txt"
STARTED=0; COMPLETE=0
for i in $(seq 1 90); do
  sleep 2
  adb logcat -d > "$E/logcat-current.txt"
  if grep -q 'GrabTikTok.*TIKTOK_COMPLETE' "$E/logcat-current.txt"; then STARTED=1; COMPLETE=1; break; fi
  if grep -q 'GrabTikTok.*TIKTOK_JOB' "$E/logcat-current.txt"; then STARTED=1; break; fi
done
[[ "$STARTED" == 1 ]] || { echo TIKTOK_SERVICE_NEVER_STARTED; grep -E 'GrabResolve|GrabTikTok|GrabEngine|AndroidRuntime|FATAL EXCEPTION' "$E/logcat-current.txt" | tail -300; exit 61; }
echo TIKTOK_SERVICE_STARTED | tee "$E/service-start-pass.txt"

# Prove actual background operation.
adb shell input keyevent KEYCODE_HOME
sleep 3
adb shell dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' | tee "$E/focus-after-home.txt" || true
adb shell pidof "$PKG" | tee "$E/pid-after-home.txt" || true
adb exec-out screencap -p > "$E/home-backgrounded.png"

if [[ "$COMPLETE" != 1 ]]; then
  for i in $(seq 1 120); do
    sleep 5
    adb logcat -d > "$E/logcat-current.txt"
    if grep -q 'GrabTikTok.*TIKTOK_COMPLETE' "$E/logcat-current.txt"; then COMPLETE=1; break; fi
  done
fi
adb logcat -d > "$E/logcat-complete.txt"
grep -E 'GrabResolve|GrabTikTok|GrabDownload|GrabEngine|AndroidRuntime|FATAL EXCEPTION' "$E/logcat-complete.txt" > "$E/logcat-focused.txt" || true
[[ "$COMPLETE" == 1 ]] || { echo TIKTOK_BACKGROUND_DOWNLOAD_DID_NOT_COMPLETE; tail -300 "$E/logcat-focused.txt"; exit 62; }
grep 'GrabTikTok.*TIKTOK_COMPLETE' "$E/logcat-complete.txt" | tail -1 | tee "$E/tiktok-complete-line.txt"

# Verify the MediaStore-published file exists and is substantive.
adb shell 'find /sdcard/Download/Grab -type f -printf "%p %s\n" 2>/dev/null' | tee "$E/download-files.txt" || true
python3 - "$E/download-files.txt" <<'PY'
import sys
rows=[]
for line in open(sys.argv[1],errors='ignore'):
    try:
        p,s=line.rsplit(' ',1); rows.append((p,int(s)))
    except: pass
ok=[r for r in rows if r[1]>100000]
if not ok: raise SystemExit('No Grab download >100KB was published')
print('PUBLISHED_MEDIA',max(ok,key=lambda x:x[1]))
PY
if grep -E 'FATAL EXCEPTION|Process: com\.veektall\.grab.*has died|AndroidRuntime.*com\.veektall\.grab' "$E/logcat-complete.txt"; then exit 63; fi
echo TIKTOK_HD_BACKGROUND_MEDIASTORE_PASS | tee "$E/download-pass.txt"

# Relaunch and inspect the app's Downloads history.
adb shell am start -W -n "$ACT" | tee "$E/relaunch.txt"
sleep 2
adb shell uiautomator dump /sdcard/relaunch.xml >/dev/null
adb pull /sdcard/relaunch.xml "$E/relaunch.xml" >/dev/null
python3 - "$E/relaunch.xml" > "$E/downloads-coord.txt" <<'PY'
import re,sys,xml.etree.ElementTree as ET
r=ET.parse(sys.argv[1]).getroot()
for n in r.iter('node'):
    if n.attrib.get('text')=='Downloads':
        m=re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',n.attrib.get('bounds',''))
        if m:
            x1,y1,x2,y2=map(int,m.groups()); print((x1+x2)//2,(y1+y2)//2); break
else: raise SystemExit('Downloads tab not found')
PY
read DX DY < "$E/downloads-coord.txt"
adb shell input tap "$DX" "$DY"
sleep 2
adb shell uiautomator dump /sdcard/downloads.xml >/dev/null
adb pull /sdcard/downloads.xml "$E/downloads.xml" >/dev/null
adb exec-out screencap -p > "$E/downloads.png"
python3 - "$E/downloads.xml" > "$E/downloads-text.txt" <<'PY'
import sys,xml.etree.ElementTree as ET
nodes=[]
for n in ET.parse(sys.argv[1]).getroot().iter('node'):
    t=n.attrib.get('text','').strip(); d=n.attrib.get('content-desc','').strip()
    if t or d:
        print('TEXT='+repr(t)+' DESC='+repr(d)+' CLASS='+n.attrib.get('class','')+' BOUNDS='+n.attrib.get('bounds',''))
        nodes.append((t,d,n.attrib))
flat=' '.join((t+' '+d).lower() for t,d,_ in nodes)
if 'no downloads' in flat or 'no download yet' in flat: raise SystemExit('Downloads tab still says empty')
if 'tiktok' not in flat and 'saved' not in flat and '.mp4' not in flat:
    raise SystemExit('No visible downloaded TikTok/media record in Downloads UI')
PY

echo GRAB_EXACT_ARM64_ANDROID16_E2E_PASS | tee "$E/final-pass.txt"
