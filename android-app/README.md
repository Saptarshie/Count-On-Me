# Count-On-Me — Android App

Offline Android port of the Real-Time Classroom Attendance & Engagement system.
The entire stack runs **on the phone** — no server, no internet needed:

```
React UI (Capacitor WebView)
        │  http://127.0.0.1:8971 (same contract as the Flask backend)
        ▼
NanoHTTPD local server  ──►  SQLite (attendance.db)
        │                       ▲
        ▼                       │
Kotlin engine: CameraX 640x480 ─┘
  ├─ MediaPipe BlazeFace (detect)          ~5-15 ms/frame
  ├─ MediaPipe FaceLandmarker (478 pts)    ~20-40 ms/frame
  ├─ SFace ONNX 128-D embeddings          ~30-60 ms/face
  ├─ Engagement: EAR + blink + head pose (exact Python formulas)
  ├─ Spatial tracking (110 px, 3 s expiry) + 3-of-5 temporal voting
  └─ Attendance: 30-min cooldown + UNIQUE(student, session) dedup
```

## Layout

```
android-app/
├── app/                    # React frontend (Vite) + Capacitor config
│   ├── src/                #  same components as ../frontend + native-mode glue
│   │   └── api.js          #  auto-targets http://127.0.0.1:8971 in the shell
│   └── android/            # native project (cap add android)
│       └── app/src/main/
│           ├── assets/     #  models + React build (public/)
│           │   ├── blaze_face_short_range.tflite
│           │   ├── face_landmarker.task
│           │   ├── face_recognition_sface.onnx   (36.9 MB, opencv_zoo)
│           │   └── public/                            (vite dist via cap sync)
│           └── java/com/countonme/attendance/
│               ├── engine/    # CameraService, MediaPipeline, FaceEmbedder (ONNX),
│               │              # EmbeddingStore, Recognizer, EngagementAnalyzer, Engine
│               ├── server/    # Database (SQLite), LocalServer (NanoHTTPD, all
│               │              # Flask-parity endpoints, SSE, MJPEG/snapshot)
│               ├── batch/     # BatchProcessor (multi-image dedup), UnknownQueue
│               └── plugins/   # SaveFilePlugin (CSV downloads via DownloadManager)
```

## Differences vs the PC backend

| | PC (Flask) | Android |
|---|---|---|
| Embedder | DeepFace VGG-Face, 4096-D | SFace ONNX **int8** (opencv_zoo), 128-D — gallery tagged per model in encodings.json, auto-invalidated on model swap |
| Match rule | cosine ≥ 0.40 | cosine ≥ 0.40 |
| Landmarks | MediaPipe Tasks Python | MediaPipe Tasks Android (same .task file) |
| Head pose | cv2.solvePnP | geometric approximation (roll from eye line, yaw/pitch from nose offsets; same thresholds & -22° pitch offset) |
| Unknown queue | `unknown/` dir | same, in app filesDir |
| Encodings | models/encodings.pkl | filesDir/encodings.json (SFace-int8) |
| SSE / MJPEG | Flask streams | NanoHTTPD chunked streams + `/video_snapshot.jpg` polling fallback for WebViews that can't render MJPEG |

Everything else — thresholds, voting, cooldowns, engagement math, endpoint
shapes, session/attendance schema, batch dedup (0.40 identify / 0.80 merge),
CSV formats — is a 1:1 port.

## Performance architecture (phone-verified on a mid-range Realme)

The Python fast/slow-path split (ref/optimisations_done.md) is preserved and
extended for phone hardware realities:

| Path | What runs | Cadence |
|---|---|---|
| Fast path | zero-copy RGBA `android.media.Image` → GPU-delegate BlazeFace | every frame (~12-20 ms) |
| Landmark mini-slow-path | GPU FaceLandmarker (blendshapes off) + per-track landmark cache | ≤7 Hz (~80-130 ms amortized) |
| Slow path | SFace int8 embed (CPU/ONNX) + cosine match | ≤1 per track per 3 s |
| Stills path | dedicated **CPU-delegate** detector for register/batch/queue (GPU EGL context is camera-bound; sharing it blocks still-image calls ~30 s) | per request |
| Snapshot | annotated JPEG (reused overlay bitmap) | 4 fps |

Measured on-device: **15-21 fps** live (from 7-10 initial), detect 12-20 ms,
real EAR/blink/head-pose telemetry, recognition/attendance verified end-to-end.

## Build (local)

Prereqs: Node 18+, JDK 21, Android SDK (platform 36, build-tools 36.0.0).

```powershell
cd android-app\app
npm install
npm run build          # vite -> dist
npx cap sync android   # dist + plugins -> android project
cd android
.\gradlew.bat assembleDebug
# APK: app\build\outputs\apk\debug\app-debug.apk
```

Optional env (defaults assume SDK on PATH / ANDROID_HOME):
`JAVA_HOME`, `ANDROID_HOME`, `GRADLE_USER_HOME`.

Release build: `.\gradlew.bat assembleRelease` (add signing config in
`app/build.gradle` first).

## Test on device

```powershell
adb install -r android-app\app\android\app\build\outputs\apk\debug\app-debug.apk
adb forward tcp:8971 tcp:8971   # optional: probe the API from your PC
curl http://127.0.0.1:8971/api/stats
```

The app auto-creates a default session on first run. Grant the camera
permission when prompted (asked at first launch).

## Cloud build (GitHub Actions)

`.github/workflows/android-build.yml` (in this folder) builds a **release APK
on push** using only GitHub-hosted runners — no local SDK needed:

```yaml
# android-app/ci/android-build.yml — copy to <repo>/.github/workflows/
```

Artifacts: `Count-On-Me-debug.apk` on every push to main.

## Batch folders on-device

The `/api/batch-attendance` folder input accepts:
- a **relative** name → resolved against the app's external files dir
  (`Android/data/com.countonme.attendance/files/`) or internal filesDir
- an absolute path the app can read (scoped storage limits most of these)

Push images for testing:
```
adb push *.jpg /sdcard/Android/data/com.countonme.attendance/files/batch_test/
```
then run with `{"folder": "batch_test"}`.

## Roadmap / known gaps

- SFace uses plain crop+resize (no 5-point alignCrop) — consistent within the
  app since the gallery is encoded by the same pipeline.
- `SaveFilePlugin` handles CSV exports via DownloadManager; `<a download>`
  fallbacks remain for browser mode.
- Google Fonts CDN is used with a system-font fallback when offline; bundle
  .woff2 files in `app/public/fonts/` for pixel-perfect offline typography.