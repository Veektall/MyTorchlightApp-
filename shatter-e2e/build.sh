#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
if [ -z "$SDK" ]; then echo "ANDROID_SDK_ROOT/ANDROID_HOME not set" >&2; exit 2; fi
BT="$SDK/build-tools/36.0.0"
ANDROID_JAR="$SDK/platforms/android-36/android.jar"
OUT="$ROOT/build"
PKG="$ROOT/app/src/main"
JAVA_DIR="$PKG/java/com/victorojo/shatterrun"
mkdir -p "$PKG/assets"
cat "$JAVA_DIR/GameModel.part00" "$JAVA_DIR/GameModel.part01" > "$JAVA_DIR/GameModel.java"
cat "$JAVA_DIR/GameView.part00" "$JAVA_DIR/GameView.part01" > "$JAVA_DIR/GameView.java"
rm -rf "$OUT" && mkdir -p "$OUT/classes" "$OUT/dex"
find "$PKG/java" -name '*.java' > "$OUT/sources.txt"
javac -source 8 -target 8 -Xlint:-options -classpath "$ANDROID_JAR" -d "$OUT/classes" @"$OUT/sources.txt"
"$BT/d8" --lib "$ANDROID_JAR" --min-api 23 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class')
"$BT/aapt" package -f -M "$PKG/AndroidManifest.xml" -I "$ANDROID_JAR" -A "$PKG/assets" -F "$OUT/app-unsigned.apk"
(cd "$OUT/dex" && "$BT/aapt" add "$OUT/app-unsigned.apk" classes.dex >/dev/null)
"$BT/zipalign" -f -p 4 "$OUT/app-unsigned.apk" "$OUT/ShatterRun-aligned.apk"
KEYSTORE="$ROOT/debug.keystore"
keytool -genkeypair -keystore "$KEYSTORE" -storepass android -keypass android -alias androiddebugkey -dname "CN=Android Debug,O=Shatter Run CI,C=US" -keyalg RSA -keysize 2048 -validity 10000 >/dev/null 2>&1
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:android --key-pass pass:android --ks-key-alias androiddebugkey --out "$OUT/ShatterRun-CI.apk" "$OUT/ShatterRun-aligned.apk"
"$BT/apksigner" verify --verbose "$OUT/ShatterRun-CI.apk"
printf 'Built: %s\n' "$OUT/ShatterRun-CI.apk"
