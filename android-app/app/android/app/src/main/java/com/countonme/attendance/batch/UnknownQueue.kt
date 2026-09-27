package com.countonme.attendance.batch

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import com.countonme.attendance.engine.EmbeddingStore
import com.countonme.attendance.engine.FaceEmbedder
import com.countonme.attendance.engine.MediaPipeline
import com.countonme.attendance.server.Database
import com.countonme.attendance.server.QueueHandler
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.sqrt

/**
 * Unknown-face review queue — 1:1 port of the Python endpoints
 * (_save_unknown_face, _cluster_unknown_faces, register/ignore flows).
 *
 * Files live in filesDir/unknown/ as JPEGs written by the engine.
 * Embeddings cached per (filename, mtime) so clusterify only embeds new crops.
 */
class UnknownQueue(
    private val appContext: Context,
    private val media: MediaPipeline,
    private val embedder: FaceEmbedder,
    private val store: EmbeddingStore,
    private val db: Database
) : QueueHandler {

    companion object {
        private const val TAG = "UnknownQueue"
        const val CLUSTER_SIM_THRESHOLD = 0.58   // Python default clusterify arg
    }

    private val embCache = ConcurrentHashMap<String, Pair<Long, FloatArray?>>()

    private fun dir(): File = File(appContext.filesDir, "unknown").apply { mkdirs() }
    private fun datasetDir(name: String): File =
        File(File(appContext.filesDir, "dataset"), name).apply { mkdirs() }

    private fun iso(ms: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(Date(ms))

    private fun files(): List<File> =
        dir().listFiles { f -> f.extension.lowercase() == "jpg" }?.sortedBy { it.name } ?: emptyList()

    // ---------------- QueueHandler ----------------

    override fun list(cluster: Boolean): Map<String, Any?> {
        val fs = files()
        val faces = fs.map { mapOf(
            "filename" to it.name,
            "url" to "/unknown/${it.name}",
            "created" to iso(it.lastModified())
        )}
        val out = LinkedHashMap<String, Any?>()
        out["unknown_faces"] = faces
        out["count"] = faces.size
        if (cluster) out["clusters"] = clustersJson(fs)
        return out
    }

    override fun clusterify(): Map<String, Any?> {
        val fs = files()
        val out = LinkedHashMap<String, Any?>()
        out["status"] = "success"
        out["count"] = fs.size
        out["clusters"] = clustersJson(fs)
        out["unclassified_count"] = 0
        return out
    }

    override fun clear(): Map<String, Any?> {
        var n = 0
        for (f in files()) { if (f.delete()) n++ }
        embCache.clear()
        return mapOf("status" to "success", "cleared" to n)
    }

    override fun register(filename: String, name: String, studentId: String, dept: String, email: String?): Map<String, Any?> =
        registerAll(listOf(filename), name, studentId, dept, email)

    override fun registerCluster(filenames: List<String>, name: String, studentId: String, dept: String, email: String?): Map<String, Any?> =
        registerAll(filenames, name, studentId, dept, email)

    override fun ignore(filenames: List<String>): Map<String, Any?> {
        var n = 0
        for (fn in filenames) {
            val f = File(dir(), File(fn).name)
            if (f.exists() && f.delete()) { n++; embCache.remove(fn) }
        }
        return mapOf("status" to "success", "removed" to n)
    }

    // ---------------- clustering ----------------

    private class Cluster(val id: String) {
        val files = ArrayList<File>()
    }

    private fun clustersJson(fs: List<File>): List<Map<String, Any?>> {
        // build clusters greedily (Python _cluster_unknown_faces)
        val clusters = ArrayList<Cluster>()
        var counter = 1
        var misc: Cluster? = null
        for (f in fs) {
            val emb = embeddingOf(f)
            if (emb == null) {
                if (misc == null) { misc = Cluster("cluster_misc"); clusters.add(misc) }
                misc!!.files.add(f)
                continue
            }
            var merged = false
            for (c in clusters) {
                if (c === misc) continue
                val best = c.files.maxOf { f2 ->
                    val e2 = embeddingOf(f2)
                    if (e2 == null) -1.0 else cosine(emb, e2)
                }
                if (best >= CLUSTER_SIM_THRESHOLD) { c.files.add(f); merged = true; break }
            }
            if (!merged) {
                val c = Cluster("Person_$counter"); counter++
                c.files.add(f)
                clusters.add(c)
            }
        }
        return clusters
            .sortedByDescending { it.files.size }
            .map { c -> mapOf(
                "cluster_id" to c.id,
                "count" to c.files.size,
                "representative" to (c.files.maxByOrNull { it.lastModified() }?.name ?: ""),
                "faces" to c.files.map { mapOf(
                    "filename" to it.name,
                    "created" to iso(it.lastModified())
                )}
            )}
    }

    // ---------------- registration ----------------

    private fun registerAll(filenames: List<String>, name: String, studentId: String, dept: String, email: String?): Map<String, Any?> {
        if (name.isBlank()) return mapOf("error" to "Name is required")
        val sid = studentId.ifBlank { name.lowercase().replace(" ", "_") }
        val vecs = ArrayList<FloatArray>()
        var moved = 0
        for (fn in filenames) {
            val src = File(dir(), File(fn).name)
            if (!src.exists()) continue
            val dst = File(datasetDir(name), "cluster_${src.name}")
            try {
                if (src.renameTo(dst)) moved++
                val bmp = BitmapFactory.decodeFile(dst.absolutePath)
                if (bmp != null) {
                    embOfBitmap(bmp)?.let { vecs.add(it) }
                    bmp.recycle()
                }
            } catch (t: Throwable) {
                Log.e(TAG, "register $fn failed", t)
            }
            embCache.remove(fn)
        }
        if (vecs.isEmpty()) {
            // record-only registration (Python allows non-encodable crops)
            db.addStudent(sid, name, email, dept)
            return mapOf(
                "status" to "success",
                "message" to "Registered $name: $moved images saved (no face encodable)",
                "encoded" to false,
                "count" to moved
            )
        }
        store.addStudent(sid, name, vecs)
        db.addStudent(sid, name, email, dept)
        return mapOf(
            "status" to "success",
            "message" to "Registered $name: $moved images saved, ${vecs.size} faces encoded",
            "encoded" to true,
            "count" to moved
        )
    }

    // ---------------- embedding helpers ----------------

    private fun embeddingOf(f: File): FloatArray? {
        val cached = embCache[f.name]
        if (cached != null && cached.first == f.lastModified()) return cached.second
        val bmp = try { BitmapFactory.decodeFile(f.absolutePath) } catch (t: Throwable) { null } ?: run {
            embCache[f.name] = f.lastModified() to null
            return null
        }
        val emb = embOfBitmap(bmp)
        bmp.recycle()
        embCache[f.name] = f.lastModified() to emb
        return emb
    }

    private fun embOfBitmap(bmp: Bitmap): FloatArray? {
        val saved = media.minFaceSize
        media.minFaceSize = 48
        try {
            val boxes = media.detect(bmp, System.currentTimeMillis())
            val b = boxes.firstOrNull() ?: return null
            val cx = b.x.coerceIn(0, bmp.width - 1)
            val cy = b.y.coerceIn(0, bmp.height - 1)
            val crop = Bitmap.createBitmap(bmp, cx, cy,
                b.w.coerceAtMost(bmp.width - cx), b.h.coerceAtMost(bmp.height - cy), null, false)
            val emb = embedder.embed(crop)
            crop.recycle()
            return emb
        } finally {
            media.minFaceSize = saved
        }
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