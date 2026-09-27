package com.countonme.attendance.engine

import android.graphics.Bitmap

/**
 * Shared data types for the recognition/engagement pipeline.
 * Mirrors the Python backend's dataclasses so behavior matches 1:1.
 */

data class FaceBox(
    val x: Int,
    val y: Int,
    val w: Int,
    val h: Int,
    val confidence: Float
) {
    val centerX: Int get() = x + w / 2
    val centerY: Int get() = y + h / 2

    /** Python backend: get_expanded_bbox(0.1) — expand by fraction on each side. */
    fun expanded(fraction: Double): FaceBox {
        val dx = (w * fraction).toInt(); val dy = (h * fraction).toInt()
        return FaceBox(x - dx, y - dy, w + 2 * dx, h + 2 * dy, confidence)
    }
}

data class HeadPose(
    val yaw: Double = 0.0,
    val pitch: Double = 0.0,
    val roll: Double = 0.0
) {
    /** Python: HeadPose.get_attention_score() — mean of per-axis attention. */
    fun attentionScore(): Double {
        val yawScore = maxOf(0.0, 100.0 - kotlin.math.abs(yaw) / YAW_THRESHOLD * 100.0)
        val pitchScore = maxOf(0.0, 100.0 - kotlin.math.abs(pitch) / PITCH_THRESHOLD * 100.0)
        val rollScore = maxOf(0.0, 100.0 - kotlin.math.abs(roll) / ROLL_THRESHOLD * 100.0)
        return (yawScore + pitchScore + rollScore) / 3.0
    }

    companion object {
        const val YAW_THRESHOLD = 30.0
        const val PITCH_THRESHOLD = 25.0
        const val ROLL_THRESHOLD = 25.0
    }
}

data class EyeMetrics(
    val leftEar: Double = 0.28,
    val rightEar: Double = 0.28,
    val averageEar: Double = 0.28,
    val isBlinking: Boolean = false,
    val eyesClosedFrames: Int = 0
) {
    /** Sleeping iff eyes closed longer than 20 consecutive frames (Python config). */
    val isSleeping: Boolean get() = eyesClosedFrames > 20
}

enum class EngagementStatus { ATTENTIVE, DISTRACTED, SLEEPING, UNKNOWN;
    override fun toString() = when (this) {
        ATTENTIVE -> "Attentive"; DISTRACTED -> "Distracted"
        SLEEPING -> "Sleeping"; UNKNOWN -> "Unknown"
    }
}

data class EngagementMetrics(
    val headPose: HeadPose = HeadPose(),
    val eyeMetrics: EyeMetrics = EyeMetrics(),
    val blinkRate: Double = 16.0,
    val engagementScore: Double = 85.0,
    val status: EngagementStatus = EngagementStatus.ATTENTIVE
) {
    fun toDict(): Map<String, Any?> = mapOf(
        "head_pose" to mapOf("yaw" to headPose.yaw, "pitch" to headPose.pitch, "roll" to headPose.roll),
        "eye_metrics" to mapOf(
            "left_ear" to eyeMetrics.leftEar,
            "right_ear" to eyeMetrics.rightEar,
            "average_ear" to eyeMetrics.averageEar,
            "is_blinking" to eyeMetrics.isBlinking
        ),
        "score" to engagementScore,
        "engagement_score" to engagementScore,
        "ear" to eyeMetrics.averageEar,
        "average_ear" to eyeMetrics.averageEar,
        "blink_rate" to blinkRate,
        "is_blinking" to eyeMetrics.isBlinking,
        "is_attentive" to (status == EngagementStatus.ATTENTIVE),
        "is_sleeping" to (status == EngagementStatus.SLEEPING),
        "status" to status.toString()
    )
}

/** One recognition outcome for a face track. */
data class RecognitionResult(
    val name: String?,
    val similarity: Double,   // cosine similarity in [0,1] (higher = better)
    val distance: Double       // 1 - similarity (Python "distance" semantics)
)

/** Mutable spatial track (Python: _tracks dict entries). */
class Track(
    @Volatile var id: Int,
    @Volatile var lastSeenMs: Long,
    @Volatile var box: FaceBox,
    @Volatile var result: RecognitionResult? = null,
    @Volatile var isKnown: Boolean = false,
    @Volatile var inFlight: Boolean = false,
    @Volatile var lastRecogMs: Long = 0,
    @Volatile var lastUnknownSaveMs: Long = 0
)

/** A student in the embedding gallery. */
data class GalleryStudent(
    val studentId: String,
    val name: String,
    val vectors: MutableList<FloatArray>   // each 128-D SFace embedding
)

/** Result of embedding one face crop. */
data class EmbedResult(
    val embedding: FloatArray,
    val box: FaceBox,
    val frameW: Int,
    val frameH: Int
)

/** Batch attendance report — same keys as Python app/batch.py. */
data class BatchReport(
    val folder: String,
    val imagesProcessed: Int,
    val facesDetected: Int,
    val uniquePeople: Int,
    val uniqueStudents: Int,
    val unknownFaces: Int,
    val duplicatesRemoved: Int,
    val avgMatchSimilarity: Double,
    val students: List<Map<String, Any>>,        // {name, present, occurrences, confidence}
    val perImage: List<Map<String, Any>>,        // {image, bbox, confidence}
    val csvPath: String?
)

/** Overlay element rendered onto the MJPEG frame. */
data class Overlay(
    val box: FaceBox,
    val name: String?,
    val similarity: Double,
    val engagementScore: Double
)