from pathlib import Path

p = Path('grab-e2e/derive_arm64_from_green.sh')
s = p.read_text(encoding='utf-8')
old = '''for n in libpython.zip.so libpython.so libqjs.so; do
  test -s "$ARM/$n"
  readelf -h "$ARM/$n" | grep 'Machine:' | tee -a "$W/out/arm64-readelf.txt"
done
test "$(grep -c 'AArch64' "$W/out/arm64-readelf.txt")" -eq 3
'''
new = '''for n in libpython.zip.so libpython.so libqjs.so; do test -s "$ARM/$n"; done
readelf -h "$ARM/libpython.so" | grep 'Machine:' | tee -a "$W/out/arm64-readelf.txt"
readelf -h "$ARM/libqjs.so" | grep 'Machine:' | tee -a "$W/out/arm64-readelf.txt"
test "$(grep -c 'AArch64' "$W/out/arm64-readelf.txt")" -eq 2
python3 - "$ARM/libpython.zip.so" <<'PY'
import sys, zipfile
if not zipfile.is_zipfile(sys.argv[1]): raise SystemExit('python runtime payload is not a zip')
print('PYTHON_ZIP_PAYLOAD_PASS')
PY
'''
if s.count(old) != 1:
    raise SystemExit('verifier anchor missing')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('ARM64_RUNTIME_VERIFIER_FIX_PASS')
