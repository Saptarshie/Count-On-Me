package com.countonme.attendance.batch

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.countonme.attendance.engine.EmbeddingStore
import com.countonme.attendance.engine.FaceEmbedder
import com.countonme.attendance.engine.MediaPipeline
import com.countonme.attendance.server.Database
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Batch (folder-of-images) attendance — 1:1 port of Python app/batch.py.
 *
 * Greedy single-pass clustering:
 *   - identify each detection against the gallery (accept at cosine >= 0.40)
 *   - identified detections merge by name
 *   - unidentified merge into first cluster with max cosine >= 0.80
 *   - CSV report to filesDir/exports/attendance_<date>.csv
 */
class BatchProcessor(
    private val appContext: Context,
    private val media: MediaPipeline,
    private val embedder: FaceEmbedder,
    private val store: EmbeddingStore,
    private val db: Database
) : com.countonme.attendance.server.BatchHandler {

    companion object {
        private const val TAG = "BatchProcessor"
        const val MAX_IMAGES = 50            // Python batch.max_images
        const val BATCH_MIN_FACE = 48        // Python batch.min_face_size
        const val DEDUP_THRESHOLD = 0.80     // Python batch.dedup_threshold
        const val IDENTIFY_MIN_SIM = 0.40    // 1.0 - recognition_threshold(0.6)
        const val MAX_DECODE_DIM = 1280
    }

    private class Detection(
        val image: String,
        val bbox: IntArray,       // x, y, w, h
        val conf: Double,
        val embedding: FloatArray
    )

    private class Cluster(
        val id: String,
        val identifiedName: String?
    ) {
        val members = ArrayList<Detection>()
        var maxSim = 0.0
    }

    override fun run(folder: String): Map<String, Any?> {
        val dir = File(folder)
        if (!dir.isDirectory) return mapOf("error" to "Folder not found: $folder")
        val files = dir.listFiles { f -> f.extension.lowercase() in setOf("jpg", "jpeg", "png") }
            ?.sortedBy { it.name } ?: emptyList()
        if (files.isEmpty()) return mapOf("error" to "No images found in folder")

        val capped = files.take(MAX_IMAGES)
        val detections = ArrayList<Detection>()
        val perImage = ArrayList<Map<String, Any>>()

        val savedMinFace = media.minFaceSize
        media.minFaceSize = BATCH_MIN_FACE
        try {
            for ((idx, f) in capped.withIndex()) {
                val bmp = decode(f) ?: continue
                val boxes = media.detect(bmp, System.currentTimeMillis() + idx)
                for (b in boxes) {
                    val cx = b.x.coerceIn(0, bmp.width - 1)
                    val cy = b.y.coerceIn(0, bmp.height - 1)
                    val cw = b.w.coerceAtMost(bmp.width - cx)
                    val ch = b.h.coerceAtMost(bmp.height - cy)
                    if (cw < BATCH_MIN_FACE || ch < BATCH_MIN_FACE) continue
                    val crop = Bitmap.createBitmap(bmp, cx, cy, cw, ch, null, false)
                    val emb = embedder.embed(crop) ?: continue
                    detections.add(Detection(f.name, intArrayOf(cx, cy, cw, ch), b.confidence.toDouble(), emb))
                    perImage.add(mapOf(
                        "image" to f.name,
                        "bbox" to listOf(cx, cy, cw, ch),
                        "confidence" to (b.confidence.toDouble() * 100).let { kotlin.math.round(it) / 100.0 }
                    ))
                    crop.recycle()
                }
                bmp.recycle()
            }
        } finally {
            media.minFaceSize = savedMinFace
        }

        // ---- greedy clustering (Python _deduplicate) ----
        val clusters = ArrayList<Cluster>()
        var personCounter = 1
        for (d in detections) {
            val match = store.match(d.embedding, IDENTIFY_MIN_SIM)
            if (match != null) {
                val c = clusters.firstOrNull { it.identifiedName == match.name }
                    ?: Cluster("known_${match.name}", match.name).also { clusters.add(it) }
                c.members.add(d)
                if (match.similarity > c.maxSim) c.maxSim = match.similarity
            } else {
                var merged = false
                for (c in clusters) {
                    if (c.identifiedName != null) continue
                    val maxSim = c.members.maxOf { cosine(it.embedding, d.embedding) }
                    if (maxSim >= DEDUP_THRESHOLD) {
                        c.members.add(d)
                        if (maxSim > c.maxSim) c.maxSim = maxSim
                        merged = true
                        break
                    }
                }
                if (!merged) {
                    val c = Cluster("Person_$personCounter", null)
                    personCounter++
                    c.members.add(d)
                    clusters.add(c)
                }
            }
        }

        val identified = clusters.filter { it.identifiedName != null }
        val unknown = clusters.filter { it.identifiedName == null }
        val avgSim = if (identified.isEmpty()) 1.0
                     else identified.map { it.maxSim }.average()

        // mark attendance in DB (Python: mark_attendance_in_db with engagement 0)
        val sid = db.activeSessionId()
        for (c in identified) {
            db.markAttendance(c.identifiedName!!, 0.0, sid)
        }

        // CSV report
        val dateStr = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val csvName = "attendance_$dateStr.csv"
        val csvFile = File(File(appContext.filesDir, "exports").apply { mkdirs() }, csvName)
        csvFile.writeText(buildString {
            appendLine("Student,Present,Occurrences,Confidence")
            for (c in identified) {
                appendLine("${c.identifiedName},YES,${c.members.size},${"%.2f".format(c.maxSim)}")
            }
        })

        return mapOf(
            "folder" to dir.absolutePath,
            "images_processed" to capped.size,
            "faces_detected" to detections.size,
            "unique_people" to clusters.size,
            "unique_students" to identified.size,
            "unknown_faces" to unknown.size,
            "duplicates_removed" to (detections.size - clusters.size),
            "avg_match_similarity" to kotlin.math.round(avgSim * 100) / 100.0,
            "students" to identified.map { mapOf(
                "name" to it.identifiedName,
                "present" to true,
                "occurrences" to it.members.size,
                "confidence" to ("%.2f".format(it.maxSim).toDouble())
            )},
            "unknown_details" to unknown.map { mapOf(
                "cluster_id" to it.id,
                "occurrences" to it.members.size,
                "avg_similarity" to "%.2f".format(it.maxSim).toDouble(),
                "images" to it.members.map { m -> m.image }.distinct()
            )},
            "per_image" to perImage,
            "csv" to csvName
        )
    }

    private fun decode(f: File): Bitmap? = try {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(f.absolutePath, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > MAX_DECODE_DIM) sample *= 2
        BitmapFactory.decodeFile(f.absolutePath, BitmapFactory.Options().apply {
            inSampleSize = sample
        })
    } catch (t: Throwable) {
        Log.e(TAG, "decode failed for ${f.name}", t)
        null
    }

    private fun cosine(a: FloatArray, b: FloatArray): Double {
        var na = 0.0; var nb = 0.0
        for (i in a.indices) { na += (a[i] * a[i]).toDouble(); nb += (b[i] * b[i]).toDouble() }
        na = sqrt(na) + 1e-10; nb = sqrt(nb) + 1e-10
        var dot = 0.0
        for (i in a.indices) dot += a[i] * b[i].toDouble()
        return dot / (na * nb)
    }
}