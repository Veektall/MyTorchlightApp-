#!/usr/bin/env bash
set -euo pipefail

mkdir -p e2e-artifacts
APK="shatter-e2e/build/ShatterRun-CI.apk"
PKG="com.victorojo.shatterrun"
ACT="com.victorojo.shatterrun/.MainActivity"

adb install -r "$APK"
adb logcat -c
adb shell am force-stop "$PKG"
adb shell am start -W -n "$ACT" | tee e2e-artifacts/launch.txt
sleep 2

dump_state() {
  local name="$1"
  adb shell uiautomator dump /sdcard/window.xml >/dev/null
  adb pull /sdcard/window.xml "e2e-artifacts/${name}.xml" >/dev/null
  adb exec-out screencap -p > "e2e-artifacts/${name}.png"
  echo "--- ${name} ---"
  grep -o 'Shatter Run[^\"]*' "e2e-artifacts/${name}.xml" || true
}

assert_state() {
  local file="$1"
  local expected="$2"
  if ! grep -q "$expected" "$file"; then
    echo "ASSERTION FAILED: expected '$expected' in $file" >&2
    cat "$file" >&2
    exit 1
  fi
}

dump_state 01_menu
assert_state e2e-artifacts/01_menu.xml 'state menu'
assert_state e2e-artifacts/01_menu.xml 'balls 25'

read -r W H < <(python3 - <<'PY'
import struct
with open('e2e-artifacts/01_menu.png','rb') as f:
    d=f.read(24)
print(*struct.unpack('>II', d[16:24]))
PY
)
echo "screen=${W}x${H}"
CX=$((W/2))
CY=$((H/2))
AIM_Y=$((H*49/100))
TOP_Y=$((H/100))
PAUSE_X=$((W*95/100))
PAUSE_Y=$((H*8/100))

# Menu -> playing.
adb shell input tap "$CX" "$CY"
sleep 0.8
dump_state 02_playing
assert_state e2e-artifacts/02_playing.xml 'state playing'
assert_state e2e-artifacts/02_playing.xml 'balls 25'

# Centerline shot collects opening crystal: 25 - 1 + 3 = 27.
adb shell input tap "$CX" "$AIM_Y"
sleep 0.9
dump_state 03_crystal
assert_state e2e-artifacts/03_crystal.xml 'state playing'
assert_state e2e-artifacts/03_crystal.xml 'crystals 1'
assert_state e2e-artifacts/03_crystal.xml 'balls 27'

# Pause and resume using the real canvas hit target.
adb shell input tap "$PAUSE_X" "$PAUSE_Y"
sleep 0.4
dump_state 04_paused
assert_state e2e-artifacts/04_paused.xml 'state paused'
adb shell input tap "$CX" "$CY"
sleep 0.4
dump_state 05_resumed
assert_state e2e-artifacts/05_resumed.xml 'state playing'

# Exhaust all balls quickly with steep upward misses. One adb shell keeps this fast
# enough that the player cannot reach the first dangerous obstacle during the loop.
adb shell "i=0; while [ \$i -lt 27 ]; do input tap $CX $TOP_Y; i=\$((i+1)); done"
sleep 4
dump_state 06_gameover
assert_state e2e-artifacts/06_gameover.xml 'state game over'
assert_state e2e-artifacts/06_gameover.xml 'balls 0'

# Game-over tap resets and immediately starts a fresh run.
adb shell input tap "$CX" "$CY"
sleep 0.6
dump_state 07_restart
assert_state e2e-artifacts/07_restart.xml 'state playing'
assert_state e2e-artifacts/07_restart.xml 'balls 25'
assert_state e2e-artifacts/07_restart.xml 'crystals 0'

adb shell pidof "$PKG" > e2e-artifacts/pid.txt
adb logcat -d > e2e-artifacts/logcat.txt
if grep -E 'FATAL EXCEPTION|Process: com\.victorojo\.shatterrun.*FATAL' e2e-artifacts/logcat.txt; then
  echo 'Crash detected' >&2
  exit 1
fi

printf 'PASS\nmenu -> playing -> crystal -> pause -> resume -> gameover -> restart\n' > e2e-artifacts/result.txt
cat e2e-artifacts/result.txt
