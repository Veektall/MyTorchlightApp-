#!/usr/bin/env bash
set -Eeuo pipefail

W=/tmp/grab-final
rm -rf "$W"
mkdir -p "$W"
cleanup(){
  rm -f "$W/session-private.pem" "$W/session-public.pem" "$W/aes.key" "$W/plain.json" \
    "$W/release.p12" "$W/password.txt" "$W/wrapped.bin" "$W/iv.bin" "$W/cipher.bin" \
    "$W/recovery-key.rsa" "$W/recovery-bundle.enc"
}
trap cleanup EXIT

ARTIFACT_ID=9197108056
UNSIGNED_SHA='9eeaa6667af9e9a0489ca1313d4c5aef06ba8943584677537751be98090bd9b8'
KEY_SHA='3a272ddc5c9c883596bbe7df67906df68f725b051dd8e5f019b99066c35b846a'
BUNDLE_SHA='68a4307b4b3a211cc2fe07c2ebc111d16a8a4944418d4d53f64c39ff980a299a'
EXPECTED_SIGNER='b3e45007cac42ff03bec33c39429a43af5d12a946c840b9062eb09b10c51ee33'
: "${GH_TOKEN:?GH_TOKEN missing}"
: "${SB_ANON:?SB_ANON missing}"

echo '=== FETCH VERIFIED ARM64 CANDIDATE ==='
gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${ARTIFACT_ID}/zip" > "$W/unsigned-artifact.zip"
mkdir -p "$W/unsigned-artifact"
unzip -q "$W/unsigned-artifact.zip" -d "$W/unsigned-artifact"
APK="$(find "$W/unsigned-artifact" -type f -name 'Grab-by-Rhoda-v3.2-X-arm64-unsigned.apk' | head -n1)"
[[ -n "$APK" && -s "$APK" ]]
cp "$APK" "$W/unsigned.apk"
echo "$UNSIGNED_SHA  $W/unsigned.apk" | sha256sum -c -

echo '=== PUBLISH ENCRYPTED RECOVERY CIPHERTEXT ==='
base64 -d .grab-release-staging/recovery-key.b64 > "$W/recovery-key.rsa"
base64 -d .grab-release-staging/recovery-bundle.b64 > "$W/recovery-bundle.enc"
echo "$KEY_SHA  $W/recovery-key.rsa" | sha256sum -c -
echo "$BUNDLE_SHA  $W/recovery-bundle.enc" | sha256sum -c -
KJ="$(curl --fail --show-error --silent --max-time 120 -X POST https://tempfile.org/api/upload/local -F "files=@$W/recovery-key.rsa;type=application/octet-stream" -F 'expiryHours=2')"
BJ="$(curl --fail --show-error --silent --max-time 120 -X POST https://tempfile.org/api/upload/local -F "files=@$W/recovery-bundle.enc;type=application/octet-stream" -F 'expiryHours=2')"
KID="$(jq -r 'if .success and (.files|length)>0 then .files[0].id else empty end' <<< "$KJ")"
BID="$(jq -r 'if .success and (.files|length)>0 then .files[0].id else empty end' <<< "$BJ")"
[[ -n "$KID" && -n "$BID" ]]
KEY_URL="https://tempfile.org/$KID/download"
BUNDLE_URL="https://tempfile.org/$BID/download"
rm -f "$W/recovery-key.rsa" "$W/recovery-bundle.enc"

echo '=== OPEN EPHEMERAL SIGNING EXCHANGE ==='
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$W/session-private.pem" >/dev/null 2>&1
openssl pkey -in "$W/session-private.pem" -pubout -out "$W/session-public.pem"
PUB_B64="$(base64 -w0 "$W/session-public.pem")"
SESSION="$(cat /proc/sys/kernel/random/uuid)"
BODY="$(printf 'SESSION_ID=%s\nSESSION_PUBLIC_KEY=%s\nRECOVERY_KEY_URL=%s\nRECOVERY_BUNDLE_URL=%s\nUNSIGNED_SHA256=%s\n' "$SESSION" "$PUB_B64" "$KEY_URL" "$BUNDLE_URL" "$UNSIGNED_SHA")"
ISSUE_URL="$(gh issue create --repo "$GITHUB_REPOSITORY" --title "grab-signing-exchange:$SESSION" --body "$BODY")"
ISSUE_NO="${ISSUE_URL##*/}"
echo "SESSION_ID=$SESSION"
echo "SIGNING_EXCHANGE_ISSUE=$ISSUE_NO"
rm -f "$W/session-public.pem"

echo '=== WAIT FOR SEALED SIGNING ENVELOPE ==='
sealed=''
for _ in $(seq 1 120); do
  R="$(curl --fail --show-error --silent "https://kwulmnvxhybbxlsdcwcn.supabase.co/rest/v1/grab_signing_envelopes?session_id=eq.${SESSION}&select=sealed" -H "apikey: $SB_ANON" -H "Authorization: Bearer $SB_ANON")"
  sealed="$(jq -c 'if length>0 then .[0].sealed else empty end' <<< "$R")"
  [[ -n "$sealed" ]] && break
  sleep 5
done
[[ -n "$sealed" ]] || { echo SIGNING_ENVELOPE_TIMEOUT; exit 70; }

jq -r '.wrapped_key' <<< "$sealed" | base64 -d > "$W/wrapped.bin"
jq -r '.iv' <<< "$sealed" | base64 -d > "$W/iv.bin"
jq -r '.ciphertext' <<< "$sealed" | base64 -d > "$W/cipher.bin"
openssl pkeyutl -decrypt -inkey "$W/session-private.pem" -in "$W/wrapped.bin" -out "$W/aes.key" \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256
node - "$W" <<'NODE'
const fs=require('fs'),crypto=require('crypto'),w=process.argv[2];
const k=fs.readFileSync(w+'/aes.key'),iv=fs.readFileSync(w+'/iv.bin'),all=fs.readFileSync(w+'/cipher.bin');
if(k.length!==32||iv.length!==12||all.length<17) throw new Error('bad envelope');
const d=crypto.createDecipheriv('aes-256-gcm',k,iv);
d.setAuthTag(all.subarray(all.length-16));
fs.writeFileSync(w+'/plain.json',Buffer.concat([d.update(all.subarray(0,all.length-16)),d.final()]));
NODE
jq -e '.v == 1 and (.p12_b64|type=="string") and (.password|type=="string")' "$W/plain.json" >/dev/null
jq -r '.p12_b64' "$W/plain.json" | base64 -d > "$W/release.p12"
jq -r '.password' "$W/plain.json" > "$W/password.txt"
chmod 600 "$W/release.p12" "$W/password.txt"
rm -f "$W/plain.json" "$W/wrapped.bin" "$W/aes.key" "$W/iv.bin" "$W/cipher.bin"

echo '=== PRODUCTION SIGN + VERIFY ==='
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}}"
SDKMANAGER="$(find "$SDK/cmdline-tools" -type f -name sdkmanager 2>/dev/null | sort -V | tail -n1)"
[[ -x "$SDKMANAGER" ]]
yes | "$SDKMANAGER" --licenses >/dev/null || true
"$SDKMANAGER" 'build-tools;36.0.0' >/dev/null
BT="$SDK/build-tools/36.0.0"
[[ -x "$BT/zipalign" && -x "$BT/apksigner" && -x "$BT/aapt" ]]
"$BT/zipalign" -P 16 -f 4 "$W/unsigned.apk" "$W/aligned.apk"
"$BT/apksigner" sign --ks "$W/release.p12" --ks-key-alias grab-release \
  --ks-pass "file:$W/password.txt" --key-pass "file:$W/password.txt" \
  --v1-signing-enabled false --v2-signing-enabled true --v3-signing-enabled true --v4-signing-enabled false \
  --out "$W/Grab-by-Rhoda-v3.2.apk" "$W/aligned.apk"
"$BT/zipalign" -c -P 16 -v 4 "$W/Grab-by-Rhoda-v3.2.apk" > "$W/zipalign-check.txt"
"$BT/apksigner" verify --verbose --print-certs "$W/Grab-by-Rhoda-v3.2.apk" > "$W/apksigner-verify.txt"
grep -q 'Verified using v2 scheme (APK Signature Scheme v2): true' "$W/apksigner-verify.txt"
grep -q 'Verified using v3 scheme (APK Signature Scheme v3): true' "$W/apksigner-verify.txt"
SIGNER="$(awk -F': ' '/Signer #1 certificate SHA-256 digest:/{print tolower($2);exit}' "$W/apksigner-verify.txt")"
[[ "$SIGNER" == "$EXPECTED_SIGNER" ]]
"$BT/aapt" dump badging "$W/Grab-by-Rhoda-v3.2.apk" > "$W/final-badging.txt"
grep -q "package: name='com.veektall.grab' versionCode='5' versionName='3.2'" "$W/final-badging.txt"
grep -q "sdkVersion:'29'" "$W/final-badging.txt"
grep -q "targetSdkVersion:'36'" "$W/final-badging.txt"
unzip -l "$W/Grab-by-Rhoda-v3.2.apk" > "$W/final-files.txt"
grep -q 'lib/arm64-v8a/' "$W/final-files.txt"
! grep -q 'lib/x86_64/' "$W/final-files.txt"
FINAL_SHA="$(sha256sum "$W/Grab-by-Rhoda-v3.2.apk" | awk '{print $1}')"
printf '%s\n' \
  'package=com.veektall.grab' \
  'versionName=3.2' \
  'versionCode=5' \
  'minSdk=29' \
  'targetSdk=36' \
  'abi=arm64-v8a' \
  "unsigned_sha256=$UNSIGNED_SHA" \
  "final_sha256=$FINAL_SHA" \
  "signer_sha256=$SIGNER" \
  'signature_v2=true' \
  'signature_v3=true' > "$W/final-manifest.txt"

J="$(curl --fail --show-error --silent --max-time 240 -X POST https://tempfile.org/api/upload/local -F "files=@$W/Grab-by-Rhoda-v3.2.apk;type=application/vnd.android.package-archive" -F 'expiryHours=24')"
ID="$(jq -r 'if .success and (.files|length)>0 then .files[0].id else empty end' <<< "$J")"
[[ -n "$ID" ]]
FINAL_URL="https://tempfile.org/$ID/download"
echo "FINAL_URL=$FINAL_URL"
echo "FINAL_SHA256=$FINAL_SHA"
echo "FINAL_SIGNER_SHA256=$SIGNER"
echo 'FINAL_SIGNING_VERIFIED_PASS'
gh issue comment "$ISSUE_NO" --repo "$GITHUB_REPOSITORY" --body "FINAL_SIGNING_VERIFIED_PASS
FINAL_URL=$FINAL_URL
FINAL_SHA256=$FINAL_SHA
FINAL_SIGNER_SHA256=$SIGNER"
gh issue close "$ISSUE_NO" --repo "$GITHUB_REPOSITORY" --reason completed
