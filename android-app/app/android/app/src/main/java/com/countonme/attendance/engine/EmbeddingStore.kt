package com.countonme.attendance.engine

import android.content.Context
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.sqrt

/**
 * Local embedding gallery, persisted as JSON (models/encodings.json in app storage).
 * Replaces Python's models/encodings.pkl — same role, Android-friendly format.
 *
 * Structure per student (mirrors pkl):
 *   { student_id, name, encodings: [[128 floats], ...], created_at }
 */
class EmbeddingStore(private val appContext: Context) {

    companion object {
        private const val TAG = "EmbeddingStore"
        private const val FILE_NAME = "encodings.json"
        /** Must match the model FaceEmbedder actually runs (int8 SFace). */
        const val MODEL_TAG = "SFace-int8"
    }

    private val students = ConcurrentHashMap<String, GalleryStudent>()
    private val lock = Any()

    fun storageFile(): File = File(appContext.filesDir, FILE_NAME)

    fun load() {
        synchronized(lock) {
            students.clear()
            val f = storageFile()
            if (!f.exists()) return
            try {
                val root = JSONObject(f.readText())
                // Model guard: int8 and fp32 embeddings live in different
                // vector spaces — a gallery encoded with the other model is
                // invalid. Drop it and require re-encoding.
                val meta = root.optJSONObject("metadata")
                val model = meta?.optString("model") ?: "SFace"
                if (model != MODEL_TAG) {
                    Log.w(TAG, "Gallery built with '$model' != '$MODEL_TAG' — discarding (re-encode needed)")
                    return
                }
                val enc = root.optJSONObject("encodings") ?: return
                val keys = enc.keys()
                while (keys.hasNext()) {
                    val sid = keys.next()
                    val o = enc.getJSONObject(sid)
                    val vecs = ArrayList<FloatArray>()
                    val arr = o.optJSONArray("encodings") ?: JSONArray()
                    for (i in 0 until arr.length()) {
                        val v = arr.getJSONArray(i)
                        val fa = FloatArray(v.length())
                        for (j in 0 until v.length()) fa[j] = v.getDouble(j).toFloat()
                        vecs.add(fa)
                    }
                    students[sid] = GalleryStudent(sid, o.optString("name", sid), vecs)
                }
                Log.i(TAG, "Loaded ${students.size} students from gallery")
            } catch (t: Throwable) {
                Log.e(TAG, "gallery load failed", t)
            }
        }
    }

    fun save() {
        synchronized(lock) {
            try {
                val enc = JSONObject()
                for ((sid, s) in students) {
                    val vecs = JSONArray()
                    for (v in s.vectors) {
                        val a = JSONArray()
                        for (f in v) a.put(f.toDouble())
                        vecs.put(a)
                    }
                    enc.put(sid, JSONObject()
                        .put("student_id", sid)
                        .put("name", s.name)
                        .put("encodings", vecs))
                }
                val root = JSONObject()
                    .put("encodings", enc)
                    .put("metadata", JSONObject()
                        .put("model", MODEL_TAG)
                        .put("total_students", students.size))
                storageFile().writeText(root.toString())
            } catch (t: Throwable) {
                Log.e(TAG, "gallery save failed", t)
            }
        }
    }

    fun addStudent(studentId: String, name: String, vectors: List<FloatArray>) {
        synchronized(lock) {
            val existing = students[studentId]
            if (existing == null) {
                students[studentId] = GalleryStudent(studentId, name, vectors.toMutableList())
            } else {
                existing.vectors.addAll(vectors)
            }
            save()
        }
    }

    fun removeStudent(studentId: String) {
        synchronized(lock) { students.remove(studentId); save() }
    }

    fun studentNames(): List<String> = students.values.map { it.name }

    fun count(): Int = students.size

    /**
     * Match an embedding against the whole gallery.
     * Python: sims = K_norm @ enc_norm; accept iff best >= 1.0 - recognition_threshold.
     * Returns (name, similarity) or null if below threshold.
     */
    fun match(embedding: FloatArray, minSimilarity: Double): RecognitionResult? {
        val enc = normalize(embedding)
        var bestName: String? = null
        var bestSim = -1.0
        // lock-free snapshot iteration over concurrent values
        for (s in students.values) {
            for (v in s.vectors) {
                val sim = cosine(enc, normalize(v))
                if (sim > bestSim) { bestSim = sim; bestName = s.name }
            }
        }
        if (bestName == null || bestSim < minSimilarity) return null
        return RecognitionResult(bestName, bestSim, 1.0 - bestSim)
    }

    /** All embeddings of one student (used by batch dedup clustering). */
    fun vectorsOf(name: String): List<FloatArray> =
        students.values.filter { it.name == name }.flatMap { it.vectors }

    private fun normalize(v: FloatArray): FloatArray {
        var norm = 0.0
        for (f in v) norm += (f * f).toDouble()
        norm = sqrt(norm) + 1e-10
        val out = FloatArray(v.size)
        for (i in v.indices) out[i] = (v[i] / norm).toFloat()
        return out
    }

    private fun cosine(a: FloatArray, b: FloatArray): Double {
        // both pre-normalized -> plain dot product (Python uses same trick)
        var dot = 0.0
        for (i in a.indices) dot += a[i] * b[i].toDouble()
        return dot
    }
}