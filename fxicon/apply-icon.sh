#!/usr/bin/env bash
set -euo pipefail

mkdir -p app/src/main/res/drawable
rm -f app/src/main/res/drawable-nodpi/fx991ms_app_icon.png 2>/dev/null || true

cat > app/src/main/res/drawable/fx991ms_app_icon.xml <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">

    <!-- calculator body -->
    <path
        android:fillColor="#16191D"
        android:pathData="M8,4 H100 V104 H8 Z" />

    <!-- subtle upper face -->
    <path
        android:fillColor="#24282D"
        android:pathData="M12,8 H96 V47 H12 Z" />

    <!-- LCD -->
    <path
        android:fillColor="#B6C6A7"
        android:pathData="M18,15 H90 V39 H18 Z" />
    <path
        android:fillColor="#1E2820"
        android:pathData="M24,22 H78 V25 H24 Z M60,30 H84 V34 H60 Z" />

    <!-- keypad row 1 -->
    <path
        android:fillColor="#697078"
        android:pathData="M16,53 H31 V64 H16 Z M36,53 H51 V64 H36 Z M56,53 H71 V64 H56 Z M76,53 H91 V64 H76 Z" />

    <!-- keypad row 2 -->
    <path
        android:fillColor="#4F555C"
        android:pathData="M16,69 H31 V80 H16 Z M36,69 H51 V80 H36 Z M56,69 H71 V80 H56 Z" />
    <path
        android:fillColor="#B84A4A"
        android:pathData="M76,69 H91 V80 H76 Z" />

    <!-- keypad row 3 -->
    <path
        android:fillColor="#4F555C"
        android:pathData="M16,85 H31 V96 H16 Z M36,85 H51 V96 H36 Z M56,85 H71 V96 H56 Z" />
    <path
        android:fillColor="#D56A55"
        android:pathData="M76,85 H91 V96 H76 Z" />
</vector>
EOF

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
p = Path('app/src/main/res/drawable/fx991ms_app_icon.xml')
assert p.exists() and p.stat().st_size > 500, 'icon generation failed'
print('Vector icon installed:', p, p.stat().st_size, 'bytes')
print(Path('app/src/main/AndroidManifest.xml').read_text(encoding='utf-8'))
PY
