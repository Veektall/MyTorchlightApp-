#!/usr/bin/env bash
set -euo pipefail
APK="${APK:-$GITHUB_WORKSPACE/candidate/fx-991MS.apk}"
PKG=com.veektall.fx991ms
ACT=.MainActivity
OUT="${OUT:-$GITHUB_WORKSPACE/e2e-out}"
XML=/data/local/tmp/fx991.xml
mkdir -p "$OUT"

echo "== device =="
adb shell getprop ro.build.version.sdk
adb shell wm size
adb install -r "$APK"
adb shell pm clear "$PKG" >/dev/null || true
adb shell wm size 420x840
adb shell wm density 160
adb shell settings put secure immersive_mode_confirmations confirmed >/dev/null 2>&1 || true
sleep 1
adb logcat -c

launch() {
  adb shell am force-stop "$PKG" || true
  adb shell am start -W -n "$PKG/$ACT" | tee "$OUT/start.txt"
  sleep 2
  adb shell pidof "$PKG" | grep -E '[0-9]+' >/dev/null
  adb shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | grep "$PKG" >/dev/null
}

dismiss_immersive_cling() {
  local xml
  xml="$(dump_lcd 2>/dev/null || true)"
  if echo "$xml" | grep -F 'Viewing full screen' >/dev/null 2>&1; then
    echo 'Dismissing Android immersive-mode tutorial'
    adb shell input tap 336 202
    sleep 1
  fi
}

dump_lcd(){
  local i xml
  for i in $(seq 1 12); do
    adb shell rm -f "$XML" >/dev/null 2>&1 || true
    if timeout 25s adb shell uiautomator dump --compressed "$XML" >/dev/null 2>&1; then
      xml="$(adb exec-out cat "$XML" 2>/dev/null | tr '\n' ' ' || true)"
      if [ -n "$xml" ] && echo "$xml" | grep -F '<hierarchy' >/dev/null 2>&1; then
        printf '%s' "$xml"
        return 0
      fi
    fi
    echo "UIAutomator dump retry $i/12" >&2
    adb shell input keyevent KEYCODE_WAKEUP >/dev/null 2>&1 || true
    sleep 1.5
  done
  echo 'UIAutomator could not obtain a root hierarchy' >&2
  adb shell dumpsys window windows > "$OUT/window-dumpsys.txt" 2>&1 || true
  adb shell dumpsys activity activities > "$OUT/activity-dumpsys.txt" 2>&1 || true
  return 1
}

assert_lcd(){
  local needle="$1" xml
  xml="$(dump_lcd)" || {
    echo "Unable to read LCD while expecting: $needle" >&2
    adb exec-out screencap -p > "$OUT/assert-failure.png" || true
    exit 20
  }
  echo "$xml" > "$OUT/window.xml"
  if ! echo "$xml" | grep -F "$needle" >/dev/null; then
    echo "Expected LCD fragment: $needle" >&2
    echo "$xml" >&2
    adb exec-out screencap -p > "$OUT/assert-failure.png" || true
    exit 21
  fi
}

launch
dismiss_immersive_cling
adb exec-out screencap -p > "$OUT/launch.png"
assert_lcd 'fx991ms LCD DEG'

tap(){ adb shell input tap "$1" "$2"; sleep 0.3; }
AC(){ tap 374 555; }
EQ(){ tap 374 725; }
AC; tap 139 668; tap 297 668; tap 139 668; EQ
sleep 0.5
assert_lcd '4'
adb exec-out screencap -p > "$OUT/2plus2.png"

AC; tap 125 396; tap 216 555; tap 262 493; EQ
sleep 0.5
assert_lcd '3'

AC; tap 262 444; tap 216 668; tap 63 725; tap 262 493; EQ
sleep 0.5
assert_lcd '0.5'

AC; tap 63 668; tap 57 396; tap 139 668; EQ
sleep 0.5
assert_lcd '0.5'
tap 57 291; tap 57 396
sleep 0.5
assert_lcd '1/2'

AC; tap 63 668; tap 216 725; tap 216 668; EQ
sleep 0.5
assert_lcd '1000'

AC; tap 295 291; tap 63 611
tap 63 668; tap 332 493; tap 374 668; tap 216 668; tap 332 493; tap 139 668; EQ
sleep 0.5
assert_lcd 'x1=2'

adb shell input swipe 295 291 295 291 900
sleep 1.5
manual_xml="$(dump_lcd)"
echo "$manual_xml" > "$OUT/manual.xml"
echo "$manual_xml" | grep -F 'fx-991MS emulator' >/dev/null
adb exec-out screencap -p > "$OUT/manual.png"
adb shell input keyevent BACK
sleep 0.5

adb shell input keyevent HOME
sleep 0.5
adb shell am start -n "$PKG/$ACT" >/dev/null
sleep 1
for i in $(seq 1 10); do launch; done

adb logcat -d > "$OUT/logcat.txt"
if grep -E 'FATAL EXCEPTION|AndroidRuntime.*Process: com\.veektall\.fx991ms' "$OUT/logcat.txt"; then
  echo "Fatal exception found" >&2
  exit 31
fi

echo "PASS Android E2E sdk=$(adb shell getprop ro.build.version.sdk)" | tee "$OUT/PASS.txt"
