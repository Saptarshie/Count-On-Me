package com.countonme.attendance.engine

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import java.util.ArrayDeque
import java.util.concurrent.ConcurrentHashMap

/**
 * Recognition orchestration replicating the Python backend exactly:
 *
 *   - Spatial centroid tracking (max association distance 110 px, tracks
 *     expire after 3.0 s unseen)
 *   - Per-track recognition cache TTL 3.0 s + in-flight dedup
 *   - Temporal voting: 3-of-5 window, "Unknown" votes ignored
 *   - Attendance marking gated by 30-min in-memory cooldown per name
 *     (cleared on session create/switch/delete) + DB unique constraint
 */
class Recognizer(
    context: Context,
    private val store: EmbeddingStore,
    private val embedder: FaceEmbedder
) {

    companion object {
        private const val TAG = "Recognizer"
        const val MAX_ASSOC_DISTANCE = 110.0          // px, Python line 375
        const val TRACK_EXPIRY_MS = 3000L             // Python 3.0 s
        const val RECOG_CACHE_TTL_MS = 3000L          // Python cache_ttl_seconds
        const val VOTE_WINDOW = 5                     // window_frames
        const val MIN_VOTES = 3                       // min_votes
        const val ATTENDANCE_COOLDOWN_MS = 30L * 60 * 1000  // 30 min
        const val DEFAULT_THRESHOLD = 0.6             // Python recognition_threshold (distance)
    }

    /** Tunables mirrored from /api/tuning */
    @Volatile var recognitionThreshold = DEFAULT_THRESHOLD

    /** The async worker executing slow-path embeddings (one at a time, like Python's single worker thread). */
    private val worker = Thread {
        while (!Thread.currentThread().isInterrupted) {
            try {
                val job = jobQueue.take()
                val crop = job.crop
                val emb = embedder.embed(crop)
                if (emb != null) {
                    val res = store.match(emb, 1.0 - recognitionThreshold)
                    job.track.result = res
                    job.track.inFlight = false
                    job.track.lastRecogMs = System.currentTimeMillis()
                    // Temporal voting (Python TemporalVotingRecognizer.observe)
                    if (res != null) observeVote(job.track, res)
                } else {
                    job.track.inFlight = false
                }
                crop.recycle()
            } catch (_: InterruptedException) {
                return@Thread
            } catch (t: Throwable) {
                Log.e(TAG, "worker error", t)
            }
        }
    }.apply { isDaemon = true; name = "recog-worker"; start() }

    private class RecogJob(val track: Track, val crop: Bitmap)

    private val jobQueue = java.util.concurrent.LinkedBlockingQueue<RecogJob>()

    // ---- Spatial tracking (Python _update_tracks, lines 356-407) ----
    private val tracks = ConcurrentHashMap<Int, Track>()
    private var nextTrackId = 1

    /** Update track states with the current frame's boxes. */
    fun updateTracks(boxes: List<FaceBox>, nowMs: Long): List<Track> {
        // expire stale
        tracks.values.removeIf { nowMs - it.lastSeenMs > TRACK_EXPIRY_MS }

        val unmatched = ArrayList(boxes)
        // greedy nearest-center association
        for (t in tracks.values) {
            var bestIdx = -1
            var bestDist = MAX_ASSOC_DISTANCE
            for (i in unmatched.indices) {
                val b = unmatched[i]
                val dx = b.centerX - t.box.centerX
                val dy = b.centerY - t.box.centerY
                val d = kotlin.math.sqrt((dx * dx + dy * dy).toDouble())
                if (d < bestDist) { bestDist = d; bestIdx = i }
            }
            if (bestIdx >= 0) {
                t.box = unmatched.removeAt(bestIdx)
                t.lastSeenMs = nowMs
            }
        }
        // spawn new tracks
        for (b in unmatched) {
            val t = Track(nextTrackId++, nowMs, b)
            tracks[t.id] = t
        }
        return tracks.values.toList()
    }

    fun activeTracks(): List<Track> = tracks.values.toList()

    /**
     * Enqueue slow-path recognition for a track if the cache expired.
     * Returns the crop bitmap to enqueue, or null (still cached / in flight).
     * Python lines 419-438.
     */
    fun maybeEnqueueRecognition(track: Track, fullFrame: Bitmap): Boolean {
        if (track.inFlight) return false
        if (System.currentTimeMillis() - track.lastRecogMs < RECOG_CACHE_TTL_MS) return false
        val crop = cropFace(fullFrame, track.box.expanded(0.1)) ?: return false
        track.inFlight = true
        if (!jobQueue.offer(RecogJob(track, crop))) track.inFlight = false
        return true
    }

    private fun cropFace(frame: Bitmap, box: FaceBox): Bitmap? {
        val x = box.x.coerceIn(0, frame.width - 1)
        val y = box.y.coerceIn(0, frame.height - 1)
        val w = box.w.coerceAtMost(frame.width - x).coerceAtLeast(8)
        val h = box.h.coerceAtMost(frame.height - y).coerceAtLeast(8)
        return Bitmap.createBitmap(frame, x, y, w, h, null, false)
    }
    private class VoteWindow {
        val sims = HashMap<String, ArrayDeque<Double>>()
    }
    private val votes = ConcurrentHashMap<Int, VoteWindow>()

    private fun observeVote(track: Track, result: RecognitionResult) {
        val w = votes.computeIfAbsent(track.id) { VoteWindow() }
        val name = result.name ?: return
        val dq = w.sims.computeIfAbsent(name) { ArrayDeque() }
        dq.addLast(result.similarity)
        // trim every candidate to last VOTE_WINDOW entries
        for ((_, v) in w.sims) while (v.size > VOTE_WINDOW) v.removeFirst()
    }

    /** Consensus name or null. Python get_consensus: winner needs >= MIN_VOTES. */
    fun consensus(track: Track): String? {
        val w = votes[track.id] ?: return null
        var bestName: String? = null
        var bestCount = 0
        for ((name, dq) in w.sims) {
            if (name == "Unknown") continue
            if (dq.size > bestCount) { bestCount = dq.size; bestName = name }
        }
        return if (bestCount >= MIN_VOTES) bestName else null
    }

    /** Current effective result for a track (consensus > cache). */
    fun resultFor(track: Track): RecognitionResult? {
        consensus(track)?.let { name ->
            return track.result?.takeIf { it.name == name } ?: RecognitionResult(name, 0.5, 0.5)
        }
        return track.result
    }

    // ---- Attendance cooldown (Python can_mark_attendance) ----
    private val attendanceLog = ConcurrentHashMap<String, Long>()

    fun canMarkAttendance(name: String): Boolean {
        val last = attendanceLog[name] ?: return true
        return System.currentTimeMillis() - last >= ATTENDANCE_COOLDOWN_MS
    }

    fun markAttendanceLogged(name: String) {
        attendanceLog[name] = System.currentTimeMillis()
    }

    fun clearCooldowns() = attendanceLog.clear()

    fun shutdown() {
        worker.interrupt()
    }
}