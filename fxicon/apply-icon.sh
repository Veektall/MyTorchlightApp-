#!/usr/bin/env bash
set -euo pipefail

mkdir -p app/src/main/res/drawable-nodpi
base64 -d fxicon/fx991ms_app_icon.png.b64 > app/src/main/res/drawable-nodpi/fx991ms_app_icon.png

python3 - <<'PY'
from pathlib import Path
import re

manifest = Path('app/src/main/AndroidManifest.xml')
s = manifest.read_text(encoding='utf-8')

if 'android:icon=' in s:
    s = re.sub(r'android:icon="[^"]+"', 'android:icon="@drawable/fx991ms_app_icon"', s, count=1)
else:
    s = s.replace('<application', '<application android:icon="@drawable/fx991ms_app_icon"', 1)

if 'android:roundIcon=' in s:
    s = re.sub(r'android:roundIcon="[^"]+"', 'android:roundIcon="@drawable/fx991ms_app_icon"', s, count=1)
else:
    s = s.replace('<application', '<application android:roundIcon="@drawable/fx991ms_app_icon"', 1)

manifest.write_text(s, encoding='utf-8')

# Bump install version so the icon build can update the previous tested build.
for name in ('app/build.gradle', 'app/build.gradle.kts'):
    p = Path(name)
    if not p.exists():
        continue
    t = p.read_text(encoding='utf-8')
    t = re.sub(r'\bversionCode\s+\d+', 'versionCode 4', t)
    t = re.sub(r'\bversionCode\s*=\s*\d+', 'versionCode = 4', t)
    t = re.sub(r'\bversionName\s+"[^"]+"', 'versionName "1.1.0"', t)
    t = re.sub(r'\bversionName\s*=\s*"[^"]+"', 'versionName = "1.1.0"', t)
    p.write_text(t, encoding='utf-8')
PY

python3 - <<'PY'
from pathlib import Path
p = Path('app/src/main/res/drawable-nodpi/fx991ms_app_icon.png')
assert p.exists() and p.stat().st_size > 1000, 'icon generation failed'
print('Icon installed:', p, p.stat().st_size, 'bytes')
print(Path('app/src/main/AndroidManifest.xml').read_text(encoding='utf-8'))
PY
