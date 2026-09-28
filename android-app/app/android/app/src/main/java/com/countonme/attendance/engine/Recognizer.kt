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
        const val RECOG_CACHE_TTL_MS = 3000L          // Python cache_ttl_seconds (post-confirm refresh)
        const val FAST_RECOG_INTERVAL_MS = 150L       // unconfirmed: sample every processed frame
        const val VOTE_WINDOW = 5                     // last N observations (4-5 consecutive frames)
        const val MIN_VOTES = 3                       // 3-of-5 majority to confirm an identity
        const val CONFIRM_SIM_FLOOR = 0.50            // junk-vote similarity floor for confirmation
        const val CHALLENGER_MIN_VOTES = 3             // fresh votes a challenger needs to unseat
        const val CHALLENGER_LEAD = 2                 // hysteresis: challenger must lead by 2
        const val ATTENDANCE_COOLDOWN_MS = 30L * 60 * 1000  // 30 min
        const val DEFAULT_THRESHOLD = 0.6             // Python recognition_threshold (distance)
    }

    /** Tunables mirrored from /api/tuning */
    @Volatile var recognitionThreshold = DEFAULT_THRESHOLD

    /**
     * Unconfirmed face candidates (Python _save_unknown_face): invoked with the
     * recognition crop when a job completes without a 3-of-5 consensus.
     * Wired by Engine to the unknown-faces review queue.
     */
    var unknownCandidateSaver: ((Bitmap, String, Double) -> Unit)? = null

    /** The async worker executing slow-path embeddings (one at a time, like Python's single worker thread). */
    private val worker = Thread {
        while (!Thread.currentThread().isInterrupted) {
            try {
                val job = jobQueue.take()
                val crop = job.crop
                val emb = embedder.embed(crop)
                if (emb != null) {
                    // Python recognize_batch parity: keep the raw best match
                    // (confidence = best similarity even when below threshold),
                    // then accept only above 1.0 - recognition_threshold.
                    val raw = store.bestMatch(emb)
                    val res = raw?.takeIf { it.similarity >= 1.0 - recognitionThreshold }
                    job.track.result = res
                    job.track.inFlight = false
                    job.track.lastRecogMs = System.currentTimeMillis()
                    // Temporal voting (Python TemporalVotingRecognizer.observe):
                    // EVERY completed job votes, including "Unknown" ones —
                    // otherwise consensus can never accumulate.
                    val accepted = observeVote(
                        job.track,
                        res?.name ?: "Unknown",
                        raw?.similarity ?: 0.0
                    )
                    // Python _save_unknown_face: unconfirmed faces with
                    // similarity >= min_confidence enter the review queue.
                    if (accepted == null && raw != null) {
                        unknownCandidateSaver?.invoke(crop, "t_${job.track.id}", raw.similarity)
                    }
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
        votes.keys.retainAll(tracks.keys)

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
    /**
     * Recognition sampling cadence: every processed frame while unidentified
     * (the majority vote needs consecutive samples fast — ~1s to confirm),
     * backing off to the Python cache TTL once the identity is confirmed.
     */
    fun needsRecognition(track: Track, nowMs: Long): Boolean {
        if (track.inFlight) return false
        val interval = if (confirmedName(track) == null) FAST_RECOG_INTERVAL_MS else RECOG_CACHE_TTL_MS
        return nowMs - track.lastRecogMs >= interval
    }

    fun maybeEnqueueRecognition(track: Track, fullFrame: Bitmap): Boolean {
        if (!needsRecognition(track, System.currentTimeMillis())) return false
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
    /**
     * Per-track identity voting: a rolling window of the last VOTE_WINDOW raw
     * observations (name, similarity). A name confirms at a MIN_VOTES-of-window
     * majority with a similarity floor. The confirmed identity is STICKY
     * (hysteresis): a challenger needs CHALLENGER_MIN_VOTES fresh votes AND a
     * CHALLENGER_LEAD advantage to unseat it — one noisy embed can never flip
     * a confirmed label. Unconfirmed tracks show "Identifying...", never a guess.
     */
    private class VoteWindow {
        val obs = ArrayDeque<Pair<String, Double>>()
        var confirmedName: String? = null
        var confirmedSim = 0.0
        val sinceConfirm = ArrayList<Pair<String, Double>>()
    }

    private val votes = ConcurrentHashMap<Int, VoteWindow>()

    /** Observe one raw recognition result. Returns the sticky confirmed name (null while unconfirmed). */
    private fun observeVote(track: Track, name: String, similarity: Double): String? {
        val w = votes.computeIfAbsent(track.id) { VoteWindow() }
        synchronized(w) {
            w.obs.addLast(name to similarity)
            while (w.obs.size > VOTE_WINDOW) w.obs.removeFirst()
            if (w.confirmedName == null) {
                confirmFromWindow(w)
            } else {
                w.sinceConfirm.add(name to similarity)
                while (w.sinceConfirm.size > VOTE_WINDOW * 2) w.sinceConfirm.removeAt(0)
                maybeSwapConfirmed(w)
            }
            return w.confirmedName
        }
    }

    private fun confirmFromWindow(w: VoteWindow) {
        val t = majority(w.obs) ?: return
        if (t.count < MIN_VOTES || t.avg < CONFIRM_SIM_FLOOR) return
        if (t.count <= t.runnerUp) return  // need a strict majority of the window
        w.confirmedName = t.name
        w.confirmedSim = t.avg
        w.sinceConfirm.clear()
    }

    private fun maybeSwapConfirmed(w: VoteWindow) {
        val confirmed = w.confirmedName ?: return
        // Fresh votes since confirmation decide whether a challenger unseats
        // the sticky identity (person-swap safety with hysteresis).
        val challengerObs = w.sinceConfirm.filter { it.first != confirmed && it.first != "Unknown" }
        val confirmedFresh = w.sinceConfirm.count { it.first == confirmed }
        val t = majority(challengerObs) ?: return
        if (t.count >= CHALLENGER_MIN_VOTES && t.count - confirmedFresh >= CHALLENGER_LEAD
            && t.avg >= CONFIRM_SIM_FLOOR) {
            w.confirmedName = t.name
            w.confirmedSim = t.avg
            w.sinceConfirm.clear()
        }
    }

    private data class Tally(val name: String, val count: Int, val avg: Double, val runnerUp: Int)

    /**
     * Best candidate over [obs] with runner-up count. Ties break on higher
     * average similarity. "Unknown" votes carry no identity and are ignored
     * (Python get_consensus parity).
     */
    private fun majority(obs: Collection<Pair<String, Double>>): Tally? {
        val counts = HashMap<String, Int>()
        val sims = HashMap<String, Double>()
        for ((n, s) in obs) {
            if (n == "Unknown") continue
            counts[n] = (counts[n] ?: 0) + 1
            sims[n] = (sims[n] ?: 0.0) + s
        }
        if (counts.isEmpty()) return null
        var best = ""
        var bestCount = -1
        var bestAvg = 0.0
        for ((n, c) in counts) {
            val avg = (sims[n] ?: 0.0) / c
            if (c > bestCount || (c == bestCount && avg > bestAvg)) {
                best = n; bestCount = c; bestAvg = avg
            }
        }
        val runnerUp = counts.filterKeys { it != best }.values.maxOrNull() ?: 0
        return Tally(best, bestCount, bestAvg, runnerUp)
    }

    /** Sticky confirmed identity for a track, or null while unconfirmed. */
    fun confirmedName(track: Track): String? = votes[track.id]?.confirmedName

    /** Current effective result for a track (sticky confirmed identity only). */
    fun resultFor(track: Track): RecognitionResult? {
        val w = votes[track.id] ?: return null
        val name = w.confirmedName ?: return null
        val sim = if (track.result?.name == name) track.result!!.similarity else w.confirmedSim
        return RecognitionResult(name, sim, 1.0 - sim)
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