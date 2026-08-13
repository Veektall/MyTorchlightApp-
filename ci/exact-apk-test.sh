#!/usr/bin/env bash
set -Eeuo pipefail
API="${1:?API required}"
E="evidence-api${API}"
mkdir -p "$E"
PACKAGE="${PACKAGE:-com.veektall.grab}"
adb wait-for-device
adb shell getprop > "$E/getprop.txt"
adb shell 'getprop ro.build.version.release; getprop ro.build.version.sdk; getprop ro.product.cpu.abi; getprop ro.product.cpu.abilist; getprop ro.dalvik.vm.native.bridge; getprop ro.enable.native.bridge.exec; getprop ro.dalvik.vm.isa.arm64' | tee "$E/device-summary.txt"
adb logcat -c
if adb install -r -t Grab.apk > "$E/install.txt" 2>&1; then
  cat "$E/install.txt"
else
  cat "$E/install.txt"
  adb logcat -d > "$E/logcat-install.txt"
  exit 21
fi
grep -q 'Success' "$E/install.txt"
adb shell pm path "$PACKAGE" | tee "$E/pm-path.txt"
adb shell am force-stop "$PACKAGE"
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 | tee "$E/launch.txt"
sleep 8
adb shell pidof "$PACKAGE" | tee "$E/pid-launch.txt"
test -s "$E/pid-launch.txt"
adb shell dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' | tee "$E/focus.txt" || true
adb shell uiautomator dump /sdcard/ui.xml || true
adb pull /sdcard/ui.xml "$E/ui.xml" || true
adb exec-out screencap -p > "$E/launch.png"
adb logcat -d > "$E/logcat-launch.txt"
if grep -E 'FATAL EXCEPTION|Fatal signal|UnsatisfiedLinkError|INSTALL_FAILED_NO_MATCHING_ABIS' "$E/logcat-launch.txt"; then exit 31; fi
adb shell 'ping -c 1 1.1.1.1' | tee "$E/ping.txt"
adb shell input keyevent KEYCODE_HOME
sleep 4
adb shell pidof "$PACKAGE" | tee "$E/pid-home.txt" || true
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 | tee "$E/relaunch.txt"
sleep 4
adb shell pidof "$PACKAGE" | tee "$E/pid-relaunch.txt"
test -s "$E/pid-relaunch.txt"
adb exec-out screencap -p > "$E/relaunch.png"
adb logcat -d > "$E/logcat-final.txt"
echo "EXACT_ARM64_EMULATOR_BASIC_PASS api=$API" | tee "$E/pass.txt"
