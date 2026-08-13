#!/usr/bin/env bash
set -Eeuo pipefail
: "${GH_TOKEN:?GH_TOKEN required}"
W=/tmp/grab-arm64-derived
rm -rf "$W"; mkdir -p "$W/green" "$W/out" "$W/repack"

gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/9189243104/zip" > "$W/green.zip"
unzip -q "$W/green.zip" -d "$W/green"
GREEN="$(find "$W/green" -type f -name 'Grab-by-Rhoda-v3.2-X-test.apk' | head -n1)"
test -n "$GREEN" && test -s "$GREEN"
cp "$GREEN" "$W/grab-x86-green.apk"
sha256sum "$W/grab-x86-green.apk" | tee "$W/out/green-sha.txt"
unzip -l "$W/grab-x86-green.apk" | grep 'lib/x86_64/' | tee "$W/out/x86-libs.txt"
test "$(grep -c 'lib/x86_64/' "$W/out/x86-libs.txt")" -eq 3

curl -fL --retry 3 --max-time 300 'https://repo1.maven.org/maven2/io/github/junkfood02/youtubedl-android/library/0.18.1/library-0.18.1.aar' -o "$W/library.aar"
test -s "$W/library.aar"
unzip -q "$W/library.aar" 'jni/arm64-v8a/*' -d "$W/aar" || true
if [[ ! -d "$W/aar/jni/arm64-v8a" ]]; then
  unzip -q "$W/library.aar" 'lib/arm64-v8a/*' -d "$W/aar" || true
fi
ARM="$W/aar/jni/arm64-v8a"; [[ -d "$ARM" ]] || ARM="$W/aar/lib/arm64-v8a"
for n in libpython.zip.so libpython.so libqjs.so; do
  test -s "$ARM/$n"
  readelf -h "$ARM/$n" | grep 'Machine:' | tee -a "$W/out/arm64-readelf.txt"
done
test "$(grep -c 'AArch64' "$W/out/arm64-readelf.txt")" -eq 3

cd "$W/repack"
unzip -q "$W/grab-x86-green.apk"
rm -rf META-INF lib/x86_64
mkdir -p lib/arm64-v8a
for n in libpython.zip.so libpython.so libqjs.so; do cp "$ARM/$n" lib/arm64-v8a/; done
zip -qr "$W/out/Grab-by-Rhoda-v3.2-X-arm64-unsigned.apk" .
unzip -l "$W/out/Grab-by-Rhoda-v3.2-X-arm64-unsigned.apk" > "$W/out/files.txt"
for n in libpython.zip.so libpython.so libqjs.so; do grep -q "lib/arm64-v8a/$n" "$W/out/files.txt"; done
! grep -q 'lib/x86_64/' "$W/out/files.txt"
sha256sum "$W/out/Grab-by-Rhoda-v3.2-X-arm64-unsigned.apk" | tee "$W/out/unsigned-sha.txt"
echo GRAB_X_ARM64_DERIVED_FROM_GREEN_UNSIGNED_PASS | tee "$W/out/result.txt"
