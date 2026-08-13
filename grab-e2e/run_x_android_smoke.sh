#!/usr/bin/env bash
set -Eeuo pipefail
: "${X_TEST_URL:?X_TEST_URL is required}"
mkdir -p evidence
adb install --no-streaming /tmp/grab-x.apk | tee evidence/install.txt
grep -q Success evidence/install.txt
adb logcat -c
adb shell am force-stop com.veektall.grab
adb shell am start -W -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "$X_TEST_URL" -n com.veektall.grab/.MainActivity | tee evidence/start.txt
PASS=0
for i in $(seq 1 30); do
  sleep 4
  adb shell uiautomator dump /sdcard/x.xml >/dev/null 2>&1 || true
  adb shell cat /sdcard/x.xml > evidence/ui.xml || true
  adb logcat -d > evidence/logcat.txt
  if grep -Fq Twitter evidence/ui.xml; then PASS=1; break; fi
done
[ "$PASS" = 1 ]
! grep -E 'FATAL EXCEPTION|AndroidRuntime.*com\.veektall\.grab' evidence/logcat.txt
echo X_TWITTER_ANDROID_RECOGNITION_PASS | tee evidence/result.txt
