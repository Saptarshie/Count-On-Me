package com.countonme.attendance.engine

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Collections

/**
 * SFace face embedder (ONNX, 128-D embeddings).
 *
 * The Python backend uses DeepFace VGG-Face (4096-D) on desktop; that model is
 * too heavy for phones, so the Android app embeds its own gallery with SFace
 * (opencv_zoo face_recognition_sface_2021dec.onnx, ~37MB, bundled in assets).
 *
 * SFace reference preprocessing (opencv_zoo sface.py):
 *   - alignCrop: 112x112 aligned crop (here approximated by a plain square crop
 *     + resize — landmark-free alignment is not available in ONNX Runtime; the
 *     app re-encodes its own gallery so pipeline consistency is preserved)
 *   - model input: 112x112x3 float32, RGB, normalized to [0,1]
 *   - cosine similarity threshold: 0.363
 */
class FaceEmbedder(context: Context) {

    companion object {
        private const val TAG = "FaceEmbedder"
        const val INPUT_SIZE = 112
        const val EMBEDDING_DIM = 128
        const val SFACE_COSINE_THRESHOLD = 0.363
    }

    private val appContext = context.applicationContext
    private var env: OrtEnvironment? = null
    private var session: OrtSession? = null

    fun warmup() { getSession() }

    private fun getSession(): OrtSession {
        session?.let { return it }
        val e = OrtEnvironment.getEnvironment()
        env = e
        // int8-quantized SFace (opencv_zoo official build): ~9.4 MB vs 36.9
        // MB fp32, faster CPU inference via XNNPACK int8 kernels. The gallery
        // is always encoded with this same model (EmbeddingStore.MODEL_TAG
        // guard), so embedding spaces stay consistent.
        val bytes = appContext.assets.open("face_recognition_sface_int8.onnx").use { it.readBytes() }
        val opts = OrtSession.SessionOptions().apply {
            setIntraOpNumThreads(2)
        }
        return e.createSession(bytes, opts).also { session = it }
    }

    /**
     * Embed a face crop. Input bitmap should be the cropped face region
     * (already clamped); it is resized to 112x112, converted RGB float32 [0,1],
     * NCHW-packed, and run through SFace.
     */
    fun embed(bitmap: Bitmap): FloatArray? {
        val s = getSession()
        val scaled = Bitmap.createScaledBitmap(bitmap, INPUT_SIZE, INPUT_SIZE, true)
        val w = INPUT_SIZE; val h = INPUT_SIZE
        val pixels = IntArray(w * h)
        scaled.getPixels(pixels, 0, w, 0, 0, w, h)
        if (scaled !== bitmap) scaled.recycle()

        val nchw = FloatArray(3 * w * h)
        var i = 0
        for (p in pixels) {
            // RGB channels, normalized to [0,1] — NCHW layout
            nchw[i] = ((p shr 16) and 0xFF) / 255f  // R
            nchw[i + w * h] = ((p shr 8) and 0xFF) / 255f   // G
            nchw[i + 2 * w * h] = (p and 0xFF) / 255f       // B
            i++
        }

        val tensorBuffer = ByteBuffer.allocateDirect(3 * w * h * 4)
            .order(ByteOrder.nativeOrder())
        tensorBuffer.asFloatBuffer().put(nchw)
        tensorBuffer.rewind()

        val shape = longArrayOf(1L, 3L, h.toLong(), w.toLong())
        val e = env ?: return null
        return try {
            OnnxTensor.createTensor(e, tensorBuffer.asFloatBuffer(), shape).use { input ->
                s.run(Collections.singletonMap(s.inputNames.iterator().next(), input)).use { output ->
                    @Suppress("UNCHECKED_CAST")
                    val raw = output[0].value as Array<FloatArray>
                    raw[0].copyOf()
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "embed failed", t)
            null
        }
    }

    fun close() {
        try { session?.close() } catch (_: Exception) {}
        session = null
    }
}