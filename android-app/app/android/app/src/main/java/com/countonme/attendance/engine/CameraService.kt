package com.countonme.attendance.engine

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.util.Log
import android.util.Size as AndroidSize
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * CameraX front-camera analyzer — decoupled preview/processing pipeline
 * (the user-visible counterpart of ref/optimisations_done.md):
 *
 *   camera (30 fps) ──► analyzer callback
 *        │  capture: raw RGBA memcpy into a 3-slot pool (~3 ms)  → STREAMER
 *        │            (video keeps flowing at camera rate)
 *        └─► processing gate (Engine, ≥50 ms) → full CV pipeline (~15-20 fps)
 *
 * The streamer thread (Engine) rotates + annotates + JPEG-encodes pool frames
 * at ~25 fps without touching the processing path, so the user sees smooth
 * video with boxes that refresh at the processing rate.
 */
class CameraService(private val context: Context) {

    companion object {
        private const val TAG = "CameraService"
        const val PROC_WIDTH = 640
        const val PROC_HEIGHT = 480
    }

    /**
     * One streaming capture slot: a reusable raw (unrotated) RGBA bitmap.
     * [busy] guards against the streamer reading while the analyzer writes.
     */
    class Slot(val w: Int, val h: Int) {
        val bmp: Bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        var rotation: Int = 0
        var ts: Long = 0
        var gen: Long = 0
        @Volatile var busy: Boolean = false
    }

    /**
     * Per-frame payload handed to the engine. [image] is only valid inside
     * onFrame (closed afterwards); [obtainBitmap] converts lazily.
     */
    /**
     * Per-frame payload handed to the engine. [image] is only valid inside
     * onFrame (closed afterwards); [obtainBitmap] converts lazily.
     */
    inner class Frame(internal val proxy: ImageProxy) {
        val width: Int get() = proxy.width
        val height: Int get() = proxy.height
        val rotationDegrees: Int get() = proxy.imageInfo.rotationDegrees

        /** Copy this frame's pixels into the streaming pool (engine-gated). */
        fun captureForStream() {
            this@CameraService.captureForStream(proxy)
        }

        /**
         * Raw YUV/RGBA android.media.Image for zero-copy MediaPipe inference.
         * Valid only inside onFrame. Separate accessor so the hot path avoids
         * Bitmap APIs entirely.
         */
        @androidx.annotation.OptIn(androidx.camera.core.ExperimentalGetImage::class)
        fun imageOrNull(): android.media.Image? = try { proxy.image } catch (t: Throwable) {
            android.util.Log.e(TAG, "image access failed", t); null
        }

        private var bitmapCache: Bitmap? = null

        /** Upright ARGB bitmap (lazily converted, cached per frame). */
        fun obtainBitmap(): Bitmap? {
            bitmapCache?.let { return it }
            val raw = try { proxy.toBitmap() } catch (t: Throwable) {
                Log.e(TAG, "toBitmap failed", t); null
            } ?: return null
            val degrees = rotationDegrees
            var bmp = raw
            if (degrees != 0) {
                val m = Matrix().apply { postRotate(degrees.toFloat()) }
                bmp = Bitmap.createBitmap(raw, 0, 0, raw.width, raw.height, m, true)
                if (bmp !== raw) raw.recycle()
            }
            bitmapCache = bmp
            return bmp
        }

        /** Upright bitmap at native rotated resolution (recog crops / stills). */
        fun obtainScaledBitmap(): Bitmap? = obtainBitmap()
    }

    interface FrameCallback {
        /** Called on the camera analyzer thread for EVERY camera frame.
         *  [frame.image] is invalid after this returns. */
        fun onFrame(frame: Frame)
    }

    private val analyzerExecutor = Executors.newSingleThreadExecutor()
    private var cameraProvider: ProcessCameraProvider? = null
    private val running = AtomicBoolean(false)

    /** Camera delivery rate (all frames, incl. skipped ones). */
    @Volatile var fps: Double = 0.0
        private set

    /** Active lens (front by default; switchable at runtime). */
    @Volatile var lensFacing: Int = CameraSelector.LENS_FACING_FRONT

    private var activeCallback: FrameCallback? = null
    private var activeLifecycle: LifecycleOwner? = null

    // ---- streaming capture pool ----
    private val poolLock = ReentrantLock()
    private val poolCond = poolLock.newCondition()
    private var slots: Array<Slot>? = null
    @Volatile private var latestSlot: Slot? = null

    fun isRunning(): Boolean = running.get()

    fun start(lifecycleOwner: LifecycleOwner, callback: FrameCallback) {
        if (running.getAndSet(true)) return
        activeCallback = callback
        activeLifecycle = lifecycleOwner
        bind()
    }

    /**
     * Flip between front and back lenses (rebinds the analyzer; the pool and
     * streaming pipeline continue seamlessly).
     */
    fun switchCamera() {
        if (!running.get()) return
        lensFacing = if (lensFacing == CameraSelector.LENS_FACING_FRONT)
            CameraSelector.LENS_FACING_BACK else CameraSelector.LENS_FACING_FRONT
        bind()
    }

    private fun bind() {
        val callback = activeCallback ?: return
        val lifecycleOwner = activeLifecycle ?: return
        val future = ProcessCameraProvider.getInstance(context)
        ContextCompat.getMainExecutor(context).execute {
            try {
                val provider = future.get()
                cameraProvider = provider

                val resolution = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(
                            AndroidSize(PROC_WIDTH, PROC_HEIGHT),
                            ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER
                        )
                    ).build()

                val analyzer = ImageAnalysis.Builder()
                    .setResolutionSelector(resolution)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    // RGBA_8888: required for MediaPipe's zero-copy MediaImage
                    // path AND lets the streaming pool memcpy pixels directly.
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()

                var fpsCounter = 0
                var fpsStartMs = System.currentTimeMillis()

                analyzer.setAnalyzer(analyzerExecutor) { imageProxy ->
                    try {
                        fpsCounter++
                        val now = System.currentTimeMillis()
                        if (now - fpsStartMs >= 1000) {
                            fps = fpsCounter * 1000.0 / (now - fpsStartMs)
                            fpsCounter = 0
                            fpsStartMs = now
                        }
                        callback.onFrame(Frame(imageProxy))
                    } catch (t: Throwable) {
                        Log.e(TAG, "frame error", t)
                    } finally {
                        imageProxy.close()
                    }
                }

                val selector = CameraSelector.Builder()
                    .requireLensFacing(lensFacing)
                    .build()

                provider.unbindAll()
                provider.bindToLifecycle(lifecycleOwner, selector, analyzer)
                Log.i(TAG, "Camera bound: lens=${if (lensFacing == CameraSelector.LENS_FACING_FRONT) "front" else "back"}")
            } catch (t: Throwable) {
                running.set(false)
                Log.e(TAG, "Camera bind failed", t)
            }
        }
    }

    // ---------------- streaming pool API (used by Engine's streamer) ----------------

    /**
     * Memcpy the raw RGBA plane into a free pool slot. Skipped silently if
     * every slot is mid-encode — the streamer simply keeps the previous frame.
     * Called by the Engine from its PROCESSING-GATED path so the camera
     * thread pays nothing between heavy frames.
     */
    fun captureForStream(proxy: ImageProxy) {
        try {
            var pool = slots
            if (pool == null) {
                pool = Array(3) { Slot(proxy.width, proxy.height) }
                slots = pool
            }
            val free = pool.firstOrNull { !it.busy } ?: return
            val plane = proxy.planes[0]
            val buf = plane.buffer
            val rowStride = plane.rowStride
            val w4 = free.w * 4
            buf.rewind()
            if (rowStride == w4) {
                free.bmp.copyPixelsFromBuffer(buf)
            } else {
                // padded rows: assemble a packed copy
                val pixels = ByteArray(w4 * free.h)
                var pos = 0
                val row = ByteArray(rowStride)
                for (y in 0 until free.h) {
                    buf.position(y * rowStride)
                    buf.get(row, 0, rowStride)
                    System.arraycopy(row, 0, pixels, pos, w4)
                    pos += w4
                }
                free.bmp.copyPixelsFromBuffer(ByteBuffer.wrap(pixels))
            }
            free.rotation = proxy.imageInfo.rotationDegrees
            free.ts = System.currentTimeMillis()
            free.gen++
            poolLock.withLock {
                latestSlot = free
                poolCond.signalAll()
            }
        } catch (t: Throwable) {
            Log.e(TAG, "captureForStream failed", t)
        }
    }

    /** Take the newest captured slot for rendering (marks it busy). */
    fun takeLatestForRender(timeoutMs: Long): Slot? {
        poolLock.withLock {
            var s = latestSlot
            if (s == null) {
                poolCond.await(timeoutMs, java.util.concurrent.TimeUnit.MILLISECONDS)
                s = latestSlot
            }
            if (s != null && !s.busy) {
                s.busy = true
                return s
            }
            return null
        }
    }

    /** Return a slot to the pool after rendering. */
    fun releaseSlot(slot: Slot) {
        poolLock.withLock { slot.busy = false }
    }

    fun stop() {
        if (!running.getAndSet(false)) return
        try {
            cameraProvider?.unbindAll()
        } catch (_: Exception) {}
        Log.i(TAG, "Camera stopped")
    }
}