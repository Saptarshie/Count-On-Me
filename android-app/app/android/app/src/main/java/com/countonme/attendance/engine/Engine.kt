package com.countonme.attendance.engine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.util.Log
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.roundToInt

/**
 * The pipeline orchestrator — mirrors Python app/__init__.py _process_frame:
 *
 *   fast path (every frame): detect -> track -> landmarks -> engagement
 *   slow path (<=1/3s per track): crop -> embed -> match -> temporal vote
 *
 * Attendance: known track + 3/5 votes + 30-min cooldown -> DB insert (delegated
 * via listener so the server layer stays decoupled).
 *
 * Also renders the annotated MJPEG snapshot (boxes + names + scores) that
 * LocalServer serves on /video_feed.
 */
class Engine(
    private val appContext: Context,
    val db: DbBridge,
    val unknownQueue: UnknownQueueBridge
) {

    companion object {
        private const val TAG = "Engine"
        const val UNKNOWN_SAVE_MIN_CONF = 0.30   // Python min_confidence
        const val UNKNOWN_SAVE_COOLDOWN_MS = 10_000L
        const val UNKNOWN_MAX_ENTRIES = 50
        const val ENGAGEMENT_WRITE_INTERVAL_MS = 3_000L  // Python DB throttle
        const val PRUNE_AFTER_MS = 4_000L
        const val HISTORY_SIZE = 90
        const val SNAPSHOT_INTERVAL_MS = 250L   // legacy snapshot cadence (now streamer-driven)
        const val LANDMARK_INTERVAL_MS = 150L   // ~7 Hz landmark refresh
        const val PROCESS_MIN_INTERVAL_MS = 125L  // CV gate: ~8 fps (thermal-friendly)
        const val PROCESS_MAX_INTERVAL_MS = 140L  // thermal-adaptive ceiling (~7 fps)
        const val STREAM_INTERVAL_MS = 33L       // streamer target: ~30 fps video
    }

    /** Snapshot throttle state. */
    @Volatile private var lastSnapshotMs = 0L
    @Volatile private var lastProcessMs = 0L

    /** Landmark mini-slow-path state: per-track cached FaceLandmarks. */
    @Volatile private var lastLandmarkMs = 0L
    private val landmarkCache = HashMap<Int, FaceLandmarks>()

    /** Latest tracks snapshot for the streamer (volatile ref swap). */
    @Volatile private var lastTracks: List<Track>? = null

    /** Reused stream-render buffers (re-allocated only on dimension change). */
    private var streamBitmap: Bitmap? = null
    private var streamW = 0
    private var streamH = 0
    private val boxPaint = Paint().apply {
        style = Paint.Style.STROKE; strokeWidth = 3f; color = Color.GREEN
    }
    private val textPaint = Paint().apply {
        color = Color.WHITE; textSize = 22f; isAntiAlias = true
    }

    /** Rolling perf counters exposed on /api/stats (diagnostics). */
    @Volatile var perfDetectMs = 0.0
    @Volatile var perfLandmarkMs = 0.0
    @Volatile var perfBitmapMs = 0.0
    @Volatile var perfFrameW = 0
    @Volatile var perfFrameH = 0

    /** DB abstraction implemented by the server layer (keeps engine decoupled). */
    interface DbBridge {
        fun markAttendance(name: String, engagementScore: Double, sessionId: String?): Boolean
        fun activeSessionId(): String?
        fun writeEngagementScore(name: String, score: Double)
        fun totalStudents(): Int
        fun presentCount(sessionId: String?): Int
    }

    /** Unknown-face queue abstraction (implemented by server layer). */
    interface UnknownQueueBridge {
        fun saveUnknownFace(jpeg: ByteArray, trackKey: String)
    }

    private val media = MediaPipeline(appContext)
    private val embedder = FaceEmbedder(appContext)
    private val store = EmbeddingStore(appContext)
    private val recognizer = Recognizer(appContext, store, embedder).apply {
        unknownCandidateSaver = { crop, key, sim -> saveUnknownCandidate(crop, key, sim) }
    }
    private val engagement = EngagementAnalyzer()
    private val camera = CameraService(appContext)

    val isRunning = AtomicBoolean(false)

    // live stats (SSE payload)
    val trackedStudents = ConcurrentHashMap<String, EngagementMetrics>()
    private val lastEngWrite = ConcurrentHashMap<String, Long>()
    private val lastUnknownSave = ConcurrentHashMap<String, Long>()
    private var lastProcessedMs = 0L
    @Volatile var fps: Double = 0.0
        private set

    /** Snapshot of the annotated frame for /video_feed. */
    @Volatile private var annotatedJpeg: ByteArray? = null

    // Tunables (server layer writes)
    @Volatile var minFaceSize = MediaPipeline.DEFAULT_MIN_FACE_SIZE
    @Volatile var minDetectionConfidence = MediaPipeline.DEFAULT_MIN_CONFIDENCE
    @Volatile var recognitionThreshold = Recognizer.DEFAULT_THRESHOLD
    @Volatile var autoAttendance = true

    fun warmup() {
        media.warmup(); embedder.warmup(); store.load()
    }

    fun recognizerBridge(): Recognizer = recognizer
    fun storeBridge(): EmbeddingStore = store
    fun cameraBridge(): CameraService = camera
    fun mediaPipeline(): MediaPipeline = media
    fun embedder(): FaceEmbedder = embedder

    fun start(lifecycleOwner: androidx.lifecycle.LifecycleOwner) {
        if (isRunning.getAndSet(true)) return
        warmup()
        camera.start(lifecycleOwner, object : CameraService.FrameCallback {
            override fun onFrame(frame: CameraService.Frame) {
                // Processing gate with THERMAL-ADAPTIVE stride (Python's
                // adaptive_skip_enabled, ported): when frame times degrade
                // (thermal throttling), widen the gate to let the SoC cool;
                // when fast, tighten back toward the base stride.
                val now = System.currentTimeMillis()
                val interval = adaptiveProcessInterval()
                if (now - lastProcessMs < interval) return
                lastProcessMs = now
                // Stream capture runs on gated frames only — the video
                // streamer keeps rendering between gates from the pool.
                frame.captureForStream()
                processFrame(frame)
            }
        })
        startStreamer()
        Log.i(TAG, "Engine started (adaptive gate ${PROCESS_MIN_INTERVAL_MS}-${PROCESS_MAX_INTERVAL_MS} ms, streamer @ ${1000 / STREAM_INTERVAL_MS} fps)")
    }

    // ---------------- thermal-adaptive gate ----------------

    /** EMA of frame process time (detect+landmark), updated per gated frame. */
    @Volatile private var processTimeEma = 0.0

    private fun adaptiveProcessInterval(): Long {
        val load = processTimeEma
        return when {
            load <= 0 -> PROCESS_MIN_INTERVAL_MS
            load > 120 -> PROCESS_MAX_INTERVAL_MS     // hot: ~7 fps processing
            load > 70 -> 130L                          // warm: ~7.5 fps
            else -> PROCESS_MIN_INTERVAL_MS           // cool: ~8 fps
        }
    }

    private fun updateProcessTimeEma(frameMs: Double) {
        processTimeEma = if (processTimeEma <= 0) frameMs
                         else 0.7 * processTimeEma + 0.3 * frameMs
    }

    fun stop() {
        if (!isRunning.getAndSet(false)) return
        stopStreamer()
        camera.stop()
        trackedStudents.clear()
        Log.i(TAG, "Engine stopped")
    }

    // ---------------- streaming renderer (smooth perceived video) ----------------

    private var streamerThread: Thread? = null
    @Volatile private var lastEncodedGen = -1L

    private fun startStreamer() {
        val t = Thread({
            while (isRunning.get()) {
                try {
                    val slot = camera.takeLatestForRender(STREAM_INTERVAL_MS + 40) ?: continue
                    try {
                        // Skip re-encoding when no new frame arrived since the
                        // last render (processing busy / camera dipped) — pure
                        // CPU waste otherwise. The client simply keeps the
                        // previous JPEG.
                        if (slot.gen != lastEncodedGen) {
                            lastEncodedGen = slot.gen
                            renderStreamFrame(slot)
                        }
                    } finally {
                        camera.releaseSlot(slot)
                    }
                    Thread.sleep(STREAM_INTERVAL_MS)
                } catch (_: InterruptedException) {
                    return@Thread
                } catch (t: Throwable) {
                    Log.e(TAG, "streamer error", t)
                }
            }
        }, "stream-renderer")
        t.isDaemon = true
        t.start()
        streamerThread = t
    }

    private fun stopStreamer() {
        streamerThread?.interrupt()
        streamerThread = null
    }

    /**
     * Rotate the captured raw frame upright (single reusable canvas — no
     * allocation), draw the LATEST boxes (updated at processing rate), and
     * JPEG-encode for /video_feed + /video_snapshot.jpg.
     */
    private fun renderStreamFrame(slot: CameraService.Slot) {
        try {
            val rot = slot.rotation
            if (streamBitmap == null || streamW != slot.w || streamH != slot.h) {
                streamBitmap?.recycle()
                streamW = slot.w; streamH = slot.h
                streamBitmap = Bitmap.createBitmap(if (rot % 180 != 0) slot.h else slot.w,
                    if (rot % 180 != 0) slot.w else slot.h, Bitmap.Config.ARGB_8888)
            }
            val bmp = streamBitmap ?: return
            val canvas = Canvas(bmp)
            canvas.save()
            val m = Matrix()
            if (rot == 90) {
                m.postRotate(90f); m.postTranslate(slot.h.toFloat(), 0f)
            } else if (rot == 180) {
                m.postRotate(180f); m.postTranslate(slot.w.toFloat(), slot.h.toFloat())
            } else if (rot == 270) {
                m.postRotate(270f); m.postTranslate(0f, slot.w.toFloat())
            }
            canvas.drawBitmap(slot.bmp, m, null)
            // draw latest boxes (refreshed by the processing thread)
            drawOverlays(canvas)
            canvas.restore()
            val jpeg = ByteArrayOutputStream(48 * 1024).use { out ->
                bmp.compress(Bitmap.CompressFormat.JPEG, 78, out); out.toByteArray()
            }
            annotatedJpeg = jpeg
        } catch (t: Throwable) {
            Log.e(TAG, "stream render failed", t)
        }
    }

    private fun drawOverlays(canvas: Canvas) {
        val tracks = lastTracks ?: return
        boxPaint.strokeWidth = 3f
        for (t in tracks) {
            val box = t.box
            canvas.drawRect(box.x.toFloat(), box.y.toFloat(),
                (box.x + box.w).toFloat(), (box.y + box.h).toFloat(), boxPaint)
            val name = recognizer.confirmedName(t)
            val label = name ?: "Identifying..."
            val score = if (name != null) trackedStudents[name]?.engagementScore else null
            val text = if (name != null && score != null) "$label (${"%.0f".format(score)}%)"
                       else label
            canvas.drawText(text, box.x + 4f, (box.y - 8).toFloat(), textPaint)
        }
    }

    fun snapshotJpeg(): ByteArray? = annotatedJpeg

    /** Flip front/back camera at runtime (stream + pipeline continue). */
    fun flipCamera(): String {
        camera.switchCamera()
        return if (camera.lensFacing == android.hardware.Camera.CameraInfo.CAMERA_FACING_FRONT) "front" else "back"
    }

    /** Register a student's face images into the gallery (live). */
    fun registerStudent(studentId: String, name: String, images: List<Bitmap>): Int {
        val vecs = ArrayList<FloatArray>()
        for (img in images) {
            val det = media.detect(img, System.currentTimeMillis())
            val box = det.firstOrNull() ?: continue
            val crop = Bitmap.createBitmap(img, box.x.coerceIn(0, img.width - 1),
                box.y.coerceIn(0, img.height - 1),
                box.w.coerceAtMost(img.width - box.x),
                box.h.coerceAtMost(img.height - box.y), null, false)
            embedder.embed(crop)?.let { vecs.add(it) }
            crop.recycle()
        }
        if (vecs.isEmpty()) return 0
        store.addStudent(studentId, name, vecs)
        return vecs.size
    }

    /**
     * Replace a student's gallery entry with fresh embeddings from [images]
     * (reference-photo add/delete). Drops both the studentId- and name-keyed
     * entries first (the legacy /api/encode path keys by directory name).
     * Empty [images] removes the student from the gallery entirely.
     */
    fun reregisterStudent(studentId: String, name: String, images: List<Bitmap>): Int {
        store.removeStudent(studentId)
        if (name != studentId) store.removeStudent(name)
        if (images.isEmpty()) return 0
        return registerStudent(studentId, name, images)
    }

    // ---------------- frame processing ----------------

    private fun processFrame(frame: CameraService.Frame) {
        val now = System.currentTimeMillis()
        fps = camera.fps
        media.minFaceSize = minFaceSize
        media.minDetectionConfidence = minDetectionConfidence
        media.rotationDegrees = frame.rotationDegrees
        recognizer.recognitionThreshold = recognitionThreshold

        // 1) FAST PATH: zero-copy detect on the raw Image (no bitmap work)
        val img = frameRawImage(frame) ?: return
        perfFrameW = frame.width
        perfFrameH = frame.height
        val t0 = System.nanoTime()
        val boxes = media.detect(img, frame.width, frame.height, now)
        val t1 = System.nanoTime()

        // 2) track (fast path, <1 ms)
        val tracks = recognizer.updateTracks(boxes, now)

        // 3) LANDMARK MINI-SLOW-PATH: the 478-pt landmarker costs ~60-90 ms
        // on phone CPUs (vs ~13 ms on the PC backend) — running it every frame
        // caps the pipeline at ~7 fps. Throttle: fresh landmarks at most every
        // LANDMARK_INTERVAL_MS (~7 Hz); between runs, per-track cached landmarks
        // feed the engagement math, which still updates EVERY frame.
        val doLandmark = boxes.isNotEmpty() && now - lastLandmarkMs >= LANDMARK_INTERVAL_MS
        val lms = if (doLandmark) {
            lastLandmarkMs = now
            media.landmark(img, frame.width, frame.height, now, boxes)
        } else emptyList()
        val t2 = System.nanoTime()
        perfDetectMs = (t1 - t0) / 1e6
        perfLandmarkMs = (t2 - t1) / 1e6
        updateProcessTimeEma(perfDetectMs + perfLandmarkMs)
        val metricsByTrack = HashMap<Int, EngagementMetrics>()
        for (i in boxes.indices) {
            val box = boxes[i]
            val owner = tracks.firstOrNull { it.box.centerX == box.centerX && it.box.centerY == box.centerY }
                ?: continue
            val lm = lms.getOrNull(i) ?: landmarkCache[owner.id]
            if (lm != null) {
                if (doLandmark) landmarkCache[owner.id] = lm
                metricsByTrack[owner.id] = engagement.update(owner, lm)
            } else {
                // No landmarks yet for this track: placeholder metrics
                // (Python app/__init__.py lines 464-471 behavior).
                metricsByTrack[owner.id] = engagement.estimate(owner, null)
            }
        }
        if (doLandmark) {
            landmarkCache.keys.retainAll { id -> tracks.any { it.id == id } }
        }
        for (t in tracks) {
            val metrics = metricsByTrack[t.id]
            if (metrics == null) { engagement.estimate(t, null); continue }
            // Python _process_frame section 6 parity: tracked_students,
            // engagement writes and attendance marking happen ONLY for is_known
            // tracks — i.e. temporal-voting consensus (3-of-5) reached.
            val name = recognizer.confirmedName(t) ?: continue
            trackedStudents[name] = metrics
            // throttled DB engagement write (Python 3 s throttle)
            val last = lastEngWrite[name] ?: 0L
            if (now - last >= ENGAGEMENT_WRITE_INTERVAL_MS) {
                lastEngWrite[name] = now
                db.writeEngagementScore(name, metrics.engagementScore)
            }
            // Attendance: consensus + 30-min cooldown + active session.
            // (Python can_mark_attendance -> mark_attendance; NOT gated behind
            // the slow-path bitmap — that was why single-face marks never fired.)
            if (autoAttendance && recognizer.canMarkAttendance(name)) {
                if (db.markAttendance(name, metrics.engagementScore, db.activeSessionId())) {
                    recognizer.markAttendanceLogged(name)
                    Log.i(TAG, "Attendance marked: $name")
                }
            }
        }
        pruneTracked(now)

        // 4) publish track state for the streamer's overlay (cheap ref swap;
        //    boxes refresh at processing rate, video at camera rate)
        lastTracks = tracks.toList()

        // 5) SLOW PATH: recognition refresh — every processed frame while a
        //    track is unidentified (fast majority sampling), backing off to the
        //    3 s cache TTL once its identity is confirmed (sticky).
        val needBitmap = tracks.any { t -> recognizer.needsRecognition(t, now) }
        if (!needBitmap) return
        val tb0 = System.nanoTime()
        val bmp = frame.obtainScaledBitmap() ?: return
        perfBitmapMs = (System.nanoTime() - tb0) / 1e6

        for (t in tracks) {
            recognizer.maybeEnqueueRecognition(t, bmp)
        }
    }

    private fun frameRawImage(frame: CameraService.Frame): android.media.Image? = try {
        frame.imageOrNull()
    } catch (t: Throwable) {
        Log.e(TAG, "raw image access failed", t)
        null
    }

    /**
     * Python _save_unknown_face parity: unconfirmed candidate faces
     * (similarity >= min_confidence, per-track cooldown) enter the review queue.
     * Invoked from the recognition worker with the actual recognition crop.
     */
    private fun saveUnknownCandidate(crop: Bitmap, trackKey: String, similarity: Double) {
        if (similarity < UNKNOWN_SAVE_MIN_CONF) return
        val now = System.currentTimeMillis()
        val last = lastUnknownSave[trackKey] ?: 0L
        if (now - last < UNKNOWN_SAVE_COOLDOWN_MS) return
        lastUnknownSave[trackKey] = now
        val jpeg = ByteArrayOutputStream().use { out ->
            crop.compress(Bitmap.CompressFormat.JPEG, 85, out); out.toByteArray()
        }
        unknownQueue.saveUnknownFace(jpeg, trackKey)
    }

    private fun pruneTracked(now: Long) {
        val stale = trackedStudents.keys.filter { name ->
            val t = recognizer.activeTracks().firstOrNull { tr -> recognizer.resultFor(tr)?.name == name }
            t == null || now - t.lastSeenMs > PRUNE_AFTER_MS
        }
        // only prune if no active track claims the name
        for (name in stale) {
            val active = recognizer.activeTracks().any { recognizer.resultFor(it)?.name == name }
            if (!active) trackedStudents.remove(name)
        }
    }

    // ---------------- SSE payload ----------------

    private val fmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.US)

    fun ssePayload(): Map<String, Any?> {
        val session = db.activeSessionId()
        val present = db.presentCount(session)
        val total = db.totalStudents()
        val tracked = trackedStudents.mapValues { it.value.toDict() }
        val avg = if (trackedStudents.isEmpty()) 0.0
                  else trackedStudents.values.map { it.engagementScore }.average()
        return mapOf(
            "is_running" to isRunning.get(),
            "fps" to fps,
            "active_session_id" to session,
            "present_count" to present,
            "total_students" to total,
            "absent_count" to (total - present).coerceAtLeast(0),
            "attendance_percentage" to if (total > 0) present * 100.0 / total else 0.0,
            "average_engagement" to kotlin.math.round(avg * 10) / 10.0,
            "tracked_students" to tracked,
            "perf" to mapOf(
                "detect_ms" to kotlin.math.round(perfDetectMs * 10) / 10.0,
                "landmark_ms" to kotlin.math.round(perfLandmarkMs * 10) / 10.0,
                "bitmap_ms" to kotlin.math.round(perfBitmapMs * 10) / 10.0,
                "frame_w" to perfFrameW,
                "frame_h" to perfFrameH
            ),
            "timestamp" to timeFmt.format(Date())
        )
    }

    fun shutdown() {
        recognizer.shutdown()
        media.close()
        embedder.close()
    }
}