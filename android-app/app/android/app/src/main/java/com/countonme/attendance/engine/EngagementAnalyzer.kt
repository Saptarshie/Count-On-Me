package com.countonme.attendance.engine

import java.util.concurrent.ConcurrentHashMap
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.sqrt

/**
 * Engagement analysis pipeline — Kotlin replica of the Python backend's
 * `app/engagement/__init__.py` (EngagementTracker + FaceMeshAnalyzer math).
 *
 * Replicated 1:1 (formulas, thresholds, smoothing):
 *  - `calculate_ear` (lines 416-455): EAR = (|p2-p6| + |p3-p5|) / (2*|p1-p4|),
 *    left eye [362,385,387,263,373,380], right eye [33,160,158,133,153,144].
 *  - `_detect_blink` (lines 774-804): eyes closed iff avg EAR < 0.25 OR both
 *    eyeBlink blendshapes > 0.55; a completed blink is 1..10 closed frames that
 *    re-open, logged only if > 0.25 s since the last logged blink.
 *  - `_calculate_blink_rate` (lines 806-827): blinks in the last 60 s; before
 *    30 s of track age, blends toward the nominal 17 bpm with an extrapolated,
 *    [8,35]-clamped count, rounded to 1 decimal.
 *  - eyes-closed counter: avg EAR < 0.21 increments, else resets (sleep iff > 20).
 *  - `_calculate_engagement_score` (lines 829-870):
 *    0.3*EAR-score + 0.4*head-score + 0.3*blink-score, clamped [0,100].
 *  - smoothing: mean of the last 90 raw scores (deque maxlen 90).
 *  - `_determine_status` (lines 872-886): sleeping > attentive (>=70) >
 *    distracted (>=40) > sleeping.
 *  - per-track state is pruned after 4 s without being seen
 *    (Python `prune_stale_tracks`, max_age_seconds=4.0).
 *
 * The only intentional deviation: head pose. The backend solves a 6-point
 * OpenCV solvePnP and decomposes the projection matrix, which is not available
 * in pure Kotlin — [estimateHeadPose] implements a stable, monotonic geometric
 * approximation instead (documented on that method).
 *
 * Thread-safety: the map is a [ConcurrentHashMap]; per-track state mutations are
 * serialized on the state instance.
 */
class EngagementAnalyzer {

    companion object {
        private const val HISTORY_SIZE = 90
        private const val PRUNE_AFTER_MS = 4_000L

        private const val DEFAULT_EAR = 0.28
        private const val EYES_CLOSED_EAR_THRESHOLD = 0.21
        private const val BLINK_EAR_THRESHOLD = 0.25
        private const val BLEND_BLINK_THRESHOLD = 0.55

        // ---- adaptive EAR calibration (Android addition) ----
        // The Python thresholds (0.25/0.21) assume a webcam at face level.
        // On a phone the camera often sits BELOW the face (held in hand) —
        // foreshortened eye geometry measures EAR ~0.10-0.19 even fully
        // open, so every open eye reads "closed". Instead of absolute
        // thresholds, judge blinks/closure relative to the track's OPEN-eye
        // EAR estimate (75th percentile of recent history).
        private const val EAR_BLINK_RATIO = 0.70          // blink iff ear < 70% of open baseline
        private const val EAR_CLOSED_RATIO = 0.58         // sustained-closed iff < 58% of baseline
        private const val EAR_BASELINE_MAX = 0.45         // sanity cap (misreads)
        private const val EAR_BASELINE_MIN = 0.08         // sanity floor
        private const val EAR_RATIO_FLOOR_BLINK = 0.13    // absolute floor: below this always counts closed
        private const val EAR_RATIO_FLOOR_CLOSED = 0.10

        private const val MIN_BLINK_GAP_MS = 250L
        private const val BLINK_MIN_CLOSED_FRAMES = 1
        private const val BLINK_MAX_CLOSED_FRAMES = 12
        private const val BLINK_TIMES_MAX = 60

        private const val BLINK_WINDOW_MS = 60_000L
        private const val WARMUP_SECONDS = 30.0
        private const val NOMINAL_BLINK_RATE = 17.0
        private const val MIN_ELAPSED_SECONDS = 5.0
        private const val BLINK_RATE_MIN_CLAMP = 8.0
        private const val BLINK_RATE_MAX_CLAMP = 35.0

        private const val NORMAL_BLINK_MIN = 15.0
        private const val NORMAL_BLINK_MAX = 20.0
        private const val EAR_WEIGHT = 0.3
        private const val HEAD_POSE_WEIGHT = 0.4
        private const val BLINK_WEIGHT = 0.3
        private const val EAR_SCORE_FULL_AT = 0.3

        private const val ATTENTIVE_THRESHOLD = 70.0
        private const val DISTRACTED_THRESHOLD = 40.0

        private val LEFT_EYE_INDICES = intArrayOf(362, 385, 387, 263, 373, 380)
        private val RIGHT_EYE_INDICES = intArrayOf(33, 160, 158, 133, 153, 144)
    }

    /** Per-track state (Python `_face_data` entries, `_get_or_create_face_data`). */
    private class TrackState(val createdAtMs: Long) {
        @Volatile var lastSeenMs: Long = createdAtMs
        val earHistory = ArrayDeque<Double>()        // deque(maxlen=history_size)
        val engagementHistory = ArrayDeque<Double>() // deque(maxlen=history_size)
        val headPoseHistory = ArrayDeque<HeadPose>() // deque(maxlen=history_size)
        val blinkTimes = ArrayDeque<Long>()          // deque(maxlen=60), epoch ms
        var eyesClosedFrames: Int = 0
        var blinkClosedFrames: Int = 0

        // adaptive EAR calibration
        var earBaseline: Double = 0.0   // latest 75th-percentile open-eye estimate
    }

    /** Per-track state keyed by track id (Python `_face_data[face_key]`). */
    private val trackStates = ConcurrentHashMap<Int, TrackState>()

    /**
     * Full engagement update for one tracked face (Python `EngagementTracker.track`
     * per-face body). Prunes stale state first, then: EAR -> blink detection ->
     * eyes-closed counter -> blink rate -> head pose -> engagement score ->
     * 90-frame smoothing -> status.
     */
    fun update(track: Track, lm: FaceLandmarks): EngagementMetrics {
        val nowMs = System.currentTimeMillis()
        prune(nowMs)
        val state = getState(track.id, nowMs)
        synchronized(state) {
            state.lastSeenMs = nowMs

            // EAR (calculate_ear, lines 416-455)
            val (leftEar, rightEar) = calculateEar(lm)
            val avgEar = (leftEar + rightEar) / 2.0
            addBounded(state.earHistory, avgEar, HISTORY_SIZE)

            // Blink detection (_detect_blink, adaptive thresholds — see header)
            val isBlinking = detectBlink(state, avgEar, lm.blendshapes, nowMs)

            // Eyes-closed counter (Python ear_threshold = 0.21; Android: also
            // percentile-relative so held-below-camera faces don't read closed)
            val closedBaseline = if (state.earBaseline > 0.0) state.earBaseline else EYES_CLOSED_EAR_THRESHOLD / EAR_CLOSED_RATIO
            val closedThresh = maxOf(closedBaseline * EAR_CLOSED_RATIO, EAR_RATIO_FLOOR_CLOSED)
            state.eyesClosedFrames =
                if (avgEar < closedThresh) state.eyesClosedFrames + 1 else 0

            // Blink rate (_calculate_blink_rate, lines 806-827)
            val blinkRate = calculateBlinkRate(state, nowMs)

            // Head pose (estimate_head_pose — geometric approximation of solvePnP)
            val headPose = estimateHeadPose(lm)
            addBounded(state.headPoseHistory, headPose, HISTORY_SIZE)

            val eyeMetrics = EyeMetrics(leftEar, rightEar, avgEar, isBlinking, state.eyesClosedFrames)

            // Engagement score (_calculate_engagement_score, lines 829-870)
            val rawScore = calculateEngagementScore(
                eyeMetrics, headPose, blinkRate,
                state.earBaseline,
                state.earBaseline > 0.0
            )

            // Smoothing: mean of last 90 raw scores
            addBounded(state.engagementHistory, rawScore, HISTORY_SIZE)
            val smoothedScore = state.engagementHistory.average()

            // Status (_determine_status, lines 872-886)
            val status = determineStatus(eyeMetrics, smoothedScore)

            return EngagementMetrics(headPose, eyeMetrics, blinkRate, smoothedScore, status)
        }
    }

    /**
     * Fallback when no landmarks are available for a track: returns the Python
     * backend's placeholder metrics (app/__init__.py lines 464-471:
     * HeadPose(0,0,0), EAR 0.28, blink rate 16.0, score 85.0, ATTENTIVE)
     * and does NOT touch any per-track state or history. With landmarks
     * present, delegates to [update].
     */
    fun estimate(track: Track, lm: FaceLandmarks?): EngagementMetrics {
        if (lm == null) {
            return EngagementMetrics(
                headPose = HeadPose(0.0, 0.0, 0.0),
                eyeMetrics = EyeMetrics(0.28, 0.28, 0.28, false, 0),
                blinkRate = 16.0,
                engagementScore = 85.0,
                status = EngagementStatus.ATTENTIVE
            )
        }
        return update(track, lm)
    }

    /** Prune tracks not seen for 4 s (Python prune_stale_tracks, max_age=4.0). */
    fun prune(nowMs: Long) {
        val it = trackStates.entries.iterator()
        while (it.hasNext()) {
            val entry = it.next()
            if (nowMs - entry.value.lastSeenMs > PRUNE_AFTER_MS) it.remove()
        }
    }

    private fun getState(trackId: Int, nowMs: Long): TrackState {
        val existing = trackStates[trackId]
        if (existing != null) return existing
        val fresh = TrackState(nowMs)
        val winner = trackStates.putIfAbsent(trackId, fresh)
        return winner ?: fresh
    }

    /**
     * calculate_ear (lines 416-455). Estimated landmarks short-circuit to
     * (0.28, 0.28); any out-of-bounds index or degenerate geometry also
     * yields 0.28 (Python catches and returns 0.28).
     */
    private fun calculateEar(lm: FaceLandmarks): Pair<Double, Double> {
        if (lm.estimated) return DEFAULT_EAR to DEFAULT_EAR
        val left = eyeAspectRatio(lm, LEFT_EYE_INDICES)
        val right = eyeAspectRatio(lm, RIGHT_EYE_INDICES)
        return left to right
    }

    /** EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|) over pixel coords. */
    private fun eyeAspectRatio(lm: FaceLandmarks, idx: IntArray): Double {
        val maxX = idx.maxOrNull() ?: return DEFAULT_EAR
        if (lm.x.size <= maxX || lm.y.size <= maxX) return DEFAULT_EAR
        val x0 = lm.x[idx[0]].toDouble(); val y0 = lm.y[idx[0]].toDouble()
        val x1 = lm.x[idx[1]].toDouble(); val y1 = lm.y[idx[1]].toDouble()
        val x2 = lm.x[idx[2]].toDouble(); val y2 = lm.y[idx[2]].toDouble()
        val x3 = lm.x[idx[3]].toDouble(); val y3 = lm.y[idx[3]].toDouble()
        val x4 = lm.x[idx[4]].toDouble(); val y4 = lm.y[idx[4]].toDouble()
        val x5 = lm.x[idx[5]].toDouble(); val y5 = lm.y[idx[5]].toDouble()
        val v1 = dist(x1, y1, x5, y5) // p2-p6
        val v2 = dist(x2, y2, x4, y4) // p3-p5
        val h = dist(x0, y0, x3, y3)  // p1-p4
        if (h < 1e-6) return DEFAULT_EAR
        return (v1 + v2) / (2.0 * h)
    }

    /** _detect_blink — with adaptive per-track EAR thresholds (see header). */
    private fun detectBlink(
        state: TrackState,
        currentEar: Double,
        blendshapes: Map<String, Double>,
        nowMs: Long
    ): Boolean {
        var blendClosed = false
        if (blendshapes.isNotEmpty()) {
            val leftB = blendshapes["eyeBlinkLeft"] ?: 0.0
            val rightB = blendshapes["eyeBlinkRight"] ?: 0.0
            if (leftB > BLEND_BLINK_THRESHOLD && rightB > BLEND_BLINK_THRESHOLD) {
                blendClosed = true
            }
        }

        // Adaptive threshold: blink iff EAR drops well below THIS person's
        // open-eye percentile (absolute floor guards broken baselines).
        val baseline = earOpenPercentile(state)
        val blinkThresh = if (baseline > 0.0) {
            maxOf(baseline * EAR_BLINK_RATIO, EAR_RATIO_FLOOR_BLINK)
        } else {
            BLINK_EAR_THRESHOLD
        }
        state.earBaseline = baseline
        val isClosed = currentEar < blinkThresh || blendClosed

        val closedFrames = state.blinkClosedFrames
        return if (isClosed) {
            state.blinkClosedFrames = closedFrames + 1
            true
        } else {
            // Eyes reopened after 1..12 closed frames (~150-1500 ms @ 8 fps) = blink
            if (closedFrames in BLINK_MIN_CLOSED_FRAMES..BLINK_MAX_CLOSED_FRAMES) {
                val lastBlink = state.blinkTimes.lastOrNull()
                if (lastBlink == null || nowMs - lastBlink > MIN_BLINK_GAP_MS) {
                    addBounded(state.blinkTimes, nowMs, BLINK_TIMES_MAX)
                }
            }
            state.blinkClosedFrames = 0
            false
        }
    }

    /**
     * Open-eye EAR estimate: 75th percentile of the track's recent EAR
     * history. Robust to brief blink dips (25% of samples may be low) and to
     * held-below-face camera foreshortening — no recursive state to mis-lock.
     */
    private fun earOpenPercentile(state: TrackState): Double {
        val hist = state.earHistory
        if (hist.size < 8) return 0.0
        val sorted = hist.toDoubleArray().also { it.sort() }
        val idx = (sorted.size * 0.75).toInt().coerceIn(0, sorted.size - 1)
        val p75 = sorted[idx]
        return p75.coerceIn(EAR_BASELINE_MIN, EAR_BASELINE_MAX)
    }

    /** _calculate_blink_rate (lines 806-827): blinks/min with warm-up ramping. */
    private fun calculateBlinkRate(state: TrackState, nowMs: Long): Double {
        val windowStartMs = nowMs - BLINK_WINDOW_MS
        val recentCount = state.blinkTimes.count { it > windowStartMs }

        val elapsedSeconds = (nowMs - state.createdAtMs) / 1000.0
        return if (elapsedSeconds < WARMUP_SECONDS) {
            val weight = maxOf(0.0, elapsedSeconds / WARMUP_SECONDS)
            val extrapolated = recentCount * (60.0 / maxOf(MIN_ELAPSED_SECONDS, elapsedSeconds))
            val clamped = extrapolated.coerceIn(BLINK_RATE_MIN_CLAMP, BLINK_RATE_MAX_CLAMP)
            round1((1.0 - weight) * NOMINAL_BLINK_RATE + weight * clamped)
        } else {
            recentCount.toDouble()
        }
    }

    /** _calculate_engagement_score (lines 829-870), weights 0.3/0.4/0.3. */
    private fun calculateEngagementScore(
        eyeMetrics: EyeMetrics,
        headPose: HeadPose,
        blinkRate: Double,
        earBaseline: Double,
        baselineReady: Boolean
    ): Double {
        // Android: score EAR relative to the learned open-eye baseline when
        // available (absolute 0.3 full-at is the Python webcam calibration).
        val earFullAt = if (baselineReady && earBaseline > EAR_BASELINE_MIN) {
            earBaseline.coerceAtLeast(0.12)
        } else {
            EAR_SCORE_FULL_AT
        }
        var earScore = minOf(100.0, eyeMetrics.averageEar / earFullAt * 100.0)
        if (eyeMetrics.isSleeping) earScore = 0.0

        val headScore = headPose.attentionScore()

        val blinkScore = when {
            blinkRate >= NORMAL_BLINK_MIN && blinkRate <= NORMAL_BLINK_MAX -> 100.0
            blinkRate < NORMAL_BLINK_MIN -> maxOf(0.0, 50.0 + blinkRate / NORMAL_BLINK_MIN * 50.0)
            else -> maxOf(0.0, 100.0 - (blinkRate - NORMAL_BLINK_MAX) * 5.0)
        }

        val engagement =
            earScore * EAR_WEIGHT + headScore * HEAD_POSE_WEIGHT + blinkScore * BLINK_WEIGHT
        return engagement.coerceIn(0.0, 100.0)
    }

    /** _determine_status (lines 872-886): >=70 attentive, >=40 distracted, else sleeping. */
    private fun determineStatus(eyeMetrics: EyeMetrics, engagementScore: Double): EngagementStatus {
        if (eyeMetrics.isSleeping) return EngagementStatus.SLEEPING
        return when {
            engagementScore >= ATTENTIVE_THRESHOLD -> EngagementStatus.ATTENTIVE
            engagementScore >= DISTRACTED_THRESHOLD -> EngagementStatus.DISTRACTED
            else -> EngagementStatus.SLEEPING
        }
    }

    /**
     * Head pose — GEOMETRIC APPROXIMATION of the backend's `estimate_head_pose`
     * (app/engagement/__init__.py lines 457-525).
     *
     * The backend runs a 6-point OpenCV solvePnP (nose tip, chin, eye corners,
     * mouth corners) against a generic 3-D face model and extracts Euler angles
     * with decomposeProjectionMatrix. OpenCV is not available in pure Kotlin, so
     * this implementation derives stable, monotonic angle proxies from the same
     * landmark geometry (all in pixel coordinates):
     *
     *  - roll: angle of the eye line (landmark 33 -> 263), atan2(dy, dx) in
     *    degrees, normalized exactly like the backend (|roll| > 90 folds to
     *    (180 - |roll|) * sign).
     *  - yaw: horizontal nose offset — the nose tip (landmark 1) x relative to
     *    the eye-corner midpoint, normalized by interocular distance and scaled
     *    to +-90 at a full eye-width of turn: yaw = (nx / eyeDist) * 90, clamped
     *    to +-90.
     *  - pitch: vertical face proportion — distance(nose, eye-midpoint) over
     *    distance(eye-midpoint, mouth-midpoint): pitch = (ratio - 0.9) * 100
     *    clamped to +-90, then the backend's pitch offset is applied:
     *    pitch = pitch - 22.0 (kept 1:1 with the Python webcam calibration).
     *
     * Estimated landmarks yield HeadPose(0, 0, 0), as in the backend.
     */
    private fun estimateHeadPose(lm: FaceLandmarks): HeadPose {
        if (lm.estimated) return HeadPose()
        if (lm.x.size < 288 || lm.y.size < 288) return HeadPose()

        val rightEyeX = lm.x[33].toDouble()
        val rightEyeY = lm.y[33].toDouble()
        val leftEyeX = lm.x[263].toDouble()
        val leftEyeY = lm.y[263].toDouble()

        val dx = leftEyeX - rightEyeX
        val dy = leftEyeY - rightEyeY
        val eyeDist = sqrt(dx * dx + dy * dy)
        if (eyeDist < 1e-6) return HeadPose()

        // Roll: eye-line angle, backend-style >90 fold normalization.
        var roll = Math.toDegrees(atan2(dy, dx))
        if (abs(roll) > 90.0) {
            roll = (180.0 - abs(roll)) * (if (roll > 0.0) 1.0 else -1.0)
        }

        // Yaw: horizontal nose offset from eye midpoint, normalized by eye distance.
        val eyeMidX = (leftEyeX + rightEyeX) / 2.0
        val eyeMidY = (leftEyeY + rightEyeY) / 2.0
        val noseX = lm.x[1].toDouble()
        val noseY = lm.y[1].toDouble()
        val nx = noseX - eyeMidX
        val yaw = ((nx / eyeDist) * 90.0).coerceIn(-90.0, 90.0)

        // Pitch: nose-to-eyeMid distance over eyeMid-to-mouthMid distance.
        val mouthMidX = (lm.x[287].toDouble() + lm.x[57].toDouble()) / 2.0
        val mouthMidY = (lm.y[287].toDouble() + lm.y[57].toDouble()) / 2.0
        val eyeToMouth = dist(eyeMidX, eyeMidY, mouthMidX, mouthMidY)
        if (eyeToMouth < 1e-6) return HeadPose() // degenerate geometry: backend falls back to HeadPose()
        val noseDy = noseY - eyeMidY
        val ratio = sqrt(nx * nx + noseDy * noseDy) / eyeToMouth
        val pitch = ((ratio - 0.9) * 100.0).coerceIn(-90.0, 90.0) - 22.0

        if (yaw.isNaN() || pitch.isNaN() || roll.isNaN()) return HeadPose()
        return HeadPose(yaw, pitch, roll)
    }

    private fun dist(x1: Double, y1: Double, x2: Double, y2: Double): Double {
        val ddx = x1 - x2
        val ddy = y1 - y2
        return sqrt(ddx * ddx + ddy * ddy)
    }

    /** Append with a maxlen bound (Python deque(maxlen=...)). */
    private fun <T> addBounded(deque: ArrayDeque<T>, item: T, maxSize: Int) {
        while (deque.size >= maxSize) deque.removeFirst()
        deque.addLast(item)
    }

    /** Round to 1 decimal (Python round(x, 1)). */
    private fun round1(value: Double): Double = Math.round(value * 10.0) / 10.0
}