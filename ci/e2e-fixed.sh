#!/usr/bin/env bash
set -euo pipefail
APK="${APK:-$GITHUB_WORKSPACE/candidate/fx-991MS.apk}"
PKG=com.veektall.fx991ms
ACT=.MainActivity
OUT="${OUT:-$GITHUB_WORKSPACE/e2e-out}"
mkdir -p "$OUT"

echo "== device =="
adb shell getprop ro.build.version.sdk
adb shell wm size
adb install -r "$APK"
adb shell pm clear "$PKG" >/dev/null || true
adb shell wm size 420x840
adb shell wm density 160
sleep 1
adb logcat -c

launch() {
  adb shell am force-stop "$PKG" || true
  adb shell am start -W -n "$PKG/$ACT" | tee "$OUT/start.txt"
  sleep 1.2
  adb shell pidof "$PKG" | grep -E '[0-9]+' >/dev/null
  adb shell dumpsys activity activities | grep -E "mResumedActivity|topResumedActivity" | grep "$PKG" >/dev/null
}

dump_lcd(){
  adb shell uiautomator dump /sdcard/fx991.xml >/dev/null
  adb shell cat /sdcard/fx991.xml | tr '\n' ' '
}
assert_lcd(){ local needle="$1"; local xml; xml="$(dump_lcd)"; echo "$xml" > "$OUT/window.xml"; echo "$xml" | grep -F "$needle" >/dev/null || { echo "Expected LCD fragment: $needle" >&2; echo "$xml" >&2; exit 21; }; }

launch
adb exec-out screencap -p > "$OUT/launch.png"
assert_lcd 'fx991ms LCD DEG'

tap(){ adb shell input tap "$1" "$2"; sleep 0.15; }
AC(){ tap 374 555; }
EQ(){ tap 374 725; }
AC; tap 139 668; tap 297 668; tap 139 668; EQ
assert_lcd '4'
adb exec-out screencap -p > "$OUT/2plus2.png"

AC; tap 125 396; tap 216 555; tap 262 493; EQ
assert_lcd '3'

AC; tap 262 444; tap 216 668; tap 63 725; tap 262 493; EQ
assert_lcd '0.5'

AC; tap 63 668; tap 57 396; tap 139 668; EQ
assert_lcd '0.5'
tap 57 291; tap 57 396
assert_lcd '1/2'

AC; tap 63 668; tap 216 725; tap 216 668; EQ
assert_lcd '1000'

AC; tap 295 291; tap 63 611
tap 63 668; tap 332 493; tap 374 668; tap 216 668; tap 332 493; tap 139 668; EQ
assert_lcd 'x1=2'

adb shell input swipe 295 291 295 291 900
sleep 1
adb shell uiautomator dump /sdcard/manual.xml >/dev/null
adb shell cat /sdcard/manual.xml | grep -F 'fx-991MS emulator' >/dev/null
adb exec-out screencap -p > "$OUT/manual.png"
adb shell input keyevent BACK

adb shell input keyevent HOME
sleep 0.5
adb shell am start -n "$PKG/$ACT" >/dev/null
sleep 0.7
for i in $(seq 1 10); do launch; done

adb logcat -d > "$OUT/logcat.txt"
if grep -E 'FATAL EXCEPTION|AndroidRuntime.*Process: com\.veektall\.fx991ms' "$OUT/logcat.txt"; then
  echo "Fatal exception found" >&2
  exit 31
fi

echo "PASS Android E2E sdk=$(adb shell getprop ro.build.version.sdk)" | tee "$OUT/PASS.txt"
