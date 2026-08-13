# Public companion workers

## Android
Create an owner-authored issue titled `public-android-worker: <label>` with JSON body:

```json
{"task":"android-gradle-debug","repo_url":"https://github.com/OWNER/REPO","ref":"main"}
```

Allowed tasks: `android-gradle-debug`, `android-gradle-release`, `apk-inspect`. The repository URL must be public GitHub.

## LuxTTS
Use the existing public Fluent LuxTTS workflows for generic CPU runtime/core packaging. Keep private voice reference material out of this repository.
