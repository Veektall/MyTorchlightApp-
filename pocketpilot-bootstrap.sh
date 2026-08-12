#!/usr/bin/env bash
set -euo pipefail
rm -rf pocketpilot
mkdir -p pocketpilot/app/src/main/java/com/pocketpilot/app pocketpilot/app/src/main/res/values pocketpilot/app/src/main/res/drawable
cat > pocketpilot/settings.gradle <<'EOF'
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }
rootProject.name = 'PocketPilot'
include ':app'
EOF
cat > pocketpilot/build.gradle <<'EOF'
plugins { id 'com.android.application' version '8.9.1' apply false }
EOF
cat > pocketpilot/gradle.properties <<'EOF'
org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.useAndroidX=true
EOF
cat > pocketpilot/app/build.gradle <<'EOF'
plugins { id 'com.android.application' }

android {
    namespace 'com.pocketpilot.app'
    compileSdk 35
    defaultConfig {
        applicationId 'com.pocketpilot.app'
        minSdk 26
        targetSdk 35
        versionCode 1
        versionName '1.0.0'
    }
}
EOF
cat > pocketpilot/app/proguard-rules.pro <<'EOF'
# PocketPilot v1 uses no code shrinking for the debug distribution build.
EOF
cat > pocketpilot/app/src/main/AndroidManifest.xml <<'EOF'
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <application android:theme="@style/AppTheme" android:label="PocketPilot" android:icon="@drawable/ic_launcher" android:allowBackup="true" android:supportsRtl="true">
        <activity android:name=".MainActivity" android:screenOrientation="portrait" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF
cat > pocketpilot/app/src/main/res/values/colors.xml <<'EOF'
<resources>
    <color name="canvas">#F6F7FB</color><color name="ink">#172033</color><color name="muted">#667085</color><color name="primary">#5B5FEF</color><color name="green">#15B897</color><color name="white">#FFFFFF</color>
</resources>
EOF
cat > pocketpilot/app/src/main/res/values/strings.xml <<'EOF'
<resources><string name="app_name">PocketPilot</string></resources>
EOF
cat > pocketpilot/app/src/main/res/values/styles.xml <<'EOF'
<resources>
    <style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar">
        <item name="android:fontFamily">sans</item><item name="android:windowActionModeOverlay">true</item><item name="android:navigationBarColor">#FFFFFF</item><item name="android:statusBarColor">#F6F7FB</item><item name="android:windowLightStatusBar">true</item><item name="android:colorAccent">#5B5FEF</item>
    </style>
</resources>
EOF
cat > pocketpilot/app/src/main/res/drawable/ic_launcher.xml <<'EOF'
<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#5B5FEF" android:pathData="M0,0h108v108h-108z"/>
    <path android:fillColor="#FFFFFF" android:pathData="M28,30h27c15,0 25,8 25,21 0,14 -10,22 -25,22h-10v15h-17zM45,44v15h9c6,0 9,-3 9,-8 0,-4 -3,-7 -9,-7z"/>
</vector>
EOF
cat pp-src/MainActivity.part*.txt > pocketpilot/app/src/main/java/com/pocketpilot/app/MainActivity.java
