package com.countonme.attendance.engine

import android.content.Context
import android.graphics.Bitmap
import android.media.Image
import android.util.Log
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.framework.image.MediaImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.core.Delegate
import com.google.mediapipe.tasks.components.containers.Category
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.facedetector.FaceDetector
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker

/**
 * MediaPipe Tasks wrappers: BlazeFace (short-range) detector + 478-pt FaceLandmarker.
 * Same models as the Python backend — bundled in APK assets.
 *
 * Performance architecture (ref/optimisations_done.md parity):
 *  - GPU delegate for both tasks (Python used CPU; phones have fast GPUs)
 *  - detect() consumes the raw android.media.Image ZERO-COPY (YUV plane
 *    handling is native inside MediaPipe — no Bitmap conversion per frame)
 *  - rotation passed via ImageProcessingOptions — no per-frame matrix rotate
 *  - landmarker only invoked when faces were detected (skip empty frames)
 *
 * Coordinate space: detector boxes are produced in the ROTATED (upright)
 * frame, mirroring the Python backend where frames are already upright.
 * When the engine needs pixel-space landmarks on a Bitmap, pass the same
 * rotation so both live in identical space.
 */
class MediaPipeline(context: Context) {

    companion object {
        private const val TAG = "MediaPipeline"
        const val MAX_FACES = 20
        const val DEFAULT_MIN_FACE_SIZE = 55
        const val DEFAULT_MIN_CONFIDENCE = 0.5f
    }

    private val appContext = context.applicationContext

    @Volatile var minFaceSize = DEFAULT_MIN_FACE_SIZE
    @Volatile var minDetectionConfidence = DEFAULT_MIN_CONFIDENCE

    private var detector: FaceDetector? = null          // GPU — live camera
    private var stillDetector: FaceDetector? = null     // CPU — register/batch/queue
    private var landmarker: FaceLandmarker? = null      // GPU — live camera

    /** Last known sensor rotation (set by Engine each frame). */
    @Volatile var rotationDegrees: Int = 0

    fun warmup() {
        getDetector(); getLandmarker(); getStillDetector()
        Log.i(TAG, "MediaPipeline warm (GPU live: BlazeFace + FaceLandmarker; CPU stills)")
    }

    private fun baseOptions(asset: String, delegate: Delegate) =
        BaseOptions.builder()
            .setModelAssetPath(asset)
            .setDelegate(delegate)
            .build()

    private fun getDetector(): FaceDetector {
        detector?.let { return it }
        val options = FaceDetector.FaceDetectorOptions.builder()
            .setBaseOptions(baseOptions("blaze_face_short_range.tflite", Delegate.GPU))
            .setMinDetectionConfidence(minDetectionConfidence)
            .setRunningMode(RunningMode.VIDEO)
            .build()
        return FaceDetector.createFromOptions(appContext, options).also { detector = it }
    }

    /**
     * CPU-delegate detector for STILL images (register, batch attendance,
     * unknown-queue embedding). The GPU delegate's EGL context is shared
     * with the live camera path — calling it from endpoint threads while
     * the camera is stopped/in flight blocks for tens of seconds. A separate
     * CPU instance makes still-image work independent and fast.
     */
    @Synchronized
    fun getStillDetector(): FaceDetector {
        stillDetector?.let { return it }
        val options = FaceDetector.FaceDetectorOptions.builder()
            .setBaseOptions(baseOptions("blaze_face_short_range.tflite", Delegate.CPU))
            .setMinDetectionConfidence(minDetectionConfidence)
            .setRunningMode(RunningMode.VIDEO)
            .build()
        return FaceDetector.createFromOptions(appContext, options).also { stillDetector = it }
    }

    private fun getLandmarker(): FaceLandmarker {
        landmarker?.let { return it }
        val options = FaceLandmarker.FaceLandmarkerOptions.builder()
            .setBaseOptions(baseOptions("face_landmarker.task", Delegate.GPU))
            .setNumFaces(MAX_FACES)
            // Blendshapes disabled for live performance: the per-face
            // blendshape head roughly doubles landmark cost on phone CPUs.
            // Blink detection still works via the EAR threshold (Python's
            // blendshape OR-condition degrades gracefully to EAR-only).
            .setOutputFaceBlendshapes(false)
            .setMinFaceDetectionConfidence(minDetectionConfidence)
            .setMinFacePresenceConfidence(0.5f)
            .setRunningMode(RunningMode.VIDEO)
            .build()
        return FaceLandmarker.createFromOptions(appContext, options).also { landmarker = it }
    }

    private fun processingOpts(): ImageProcessingOptions =
        ImageProcessingOptions.builder()
            .setRotationDegrees(rotationDegrees)
            .build()

    /**
     * ZERO-COPY detect on the raw camera Image (YUV->RGBA by CameraX).
     *
     * IMPORTANT coordinate-space contract: when rotation is passed via
     * ImageProcessingOptions, MediaPipe normalizes landmarks against the
     * ROTATED image but maps pixel detection boxes BACK to the ORIGINAL
     * unrotated frame. To keep the whole pipeline (tracking, landmark
     * matching, crops, overlay) in ONE consistent UPRIGHT space, we rotate
     * the returned boxes original -> upright here.
     */
    fun detect(image: Image, imageW: Int, imageH: Int, timestampMs: Long): List<FaceBox> {
        val mpImage = MediaImageBuilder(image).build()
        val result = try {
            getDetector().detectForVideo(mpImage, processingOpts(), timestampMs)
        } catch (t: Throwable) {
            Log.e(TAG, "detect failed", t)
            return emptyList()
        }
        // Upright (rotated) dims
        val rotated = rotationDegrees % 180 != 0
        val upW = if (rotated) imageH else imageW
        val upH = if (rotated) imageW else imageH
        val boxes = ArrayList<FaceBox>(result.detections().size)
        for (d in result.detections()) {
            val conf = d.categories().firstOrNull()?.score() ?: 0.5f
            val up = rotateBoxToUpright(d.boundingBox(), imageW, imageH, rotationDegrees)
            // clamp to upright frame (Python parity)
            val left = up[0].coerceIn(0, upW - 1)
            val top = up[1].coerceIn(0, upH - 1)
            val bw = up[2].coerceAtMost(upW - left)
            val bh = up[3].coerceAtMost(upH - top)
            if (bw < minFaceSize || bh < minFaceSize) continue
            boxes.add(FaceBox(left, top, bw, bh, conf))
        }
        return boxes
    }

    /**
     * Rotate an ORIGINAL-frame pixel box into the UPRIGHT frame.
     * MediaPipe maps detections back to the original (unrotated) image when
     * ImageProcessingOptions.rotationDegrees is set; the rest of the engine
     * operates on the upright bitmap, so remap here.
     * Returns [left, top, width, height] in upright pixels.
     */
    private fun rotateBoxToUpright(bb: android.graphics.RectF, W: Int, H: Int, rotation: Int): IntArray {
        val l = bb.left; val t = bb.top; val r = bb.right; val b = bb.bottom
        return when (((rotation % 360) + 360) % 360) {
            90 -> intArrayOf(
                (H - b).toInt(),          // x' = H - y
                l.toInt(),                // y' = x
                (b - t).toInt(),
                (r - l).toInt()
            )
            180 -> intArrayOf(
                (W - r).toInt(), (H - b).toInt(),
                (r - l).toInt(), (b - t).toInt()
            )
            270 -> intArrayOf(
                t.toInt(),                // x' = y
                (W - r).toInt(),          // y' = W - x
                (b - t).toInt(),
                (r - l).toInt()
            )
            else -> intArrayOf(l.toInt(), t.toInt(), (r - l).toInt(), (b - t).toInt())
        }
    }

    /** Bitmap-based detect (still images: register/batch/queue — CPU path). */
    fun detect(bitmap: Bitmap, timestampMs: Long): List<FaceBox> {
        val mpImage = BitmapImageBuilder(bitmap).build()
        val result = try {
            getStillDetector().detectForVideo(mpImage, timestampMs)
        } catch (t: Throwable) {
            Log.e(TAG, "detect failed", t)
            return emptyList()
        }
        val w = bitmap.width
        val h = bitmap.height
        val boxes = ArrayList<FaceBox>(result.detections().size)
        for (d in result.detections()) {
            val bb = d.boundingBox()
            val left = bb.left.toInt().coerceIn(0, w - 1)
            val top = bb.top.toInt().coerceIn(0, h - 1)
            val bw = (bb.right - bb.left).toInt().coerceAtMost(w - left)
            val bh = (bb.bottom - bb.top).toInt().coerceAtMost(h - top)
            if (bw < minFaceSize || bh < minFaceSize) continue
            val conf = d.categories().firstOrNull()?.score() ?: 0.5f
            boxes.add(FaceBox(left, top, bw, bh, conf))
        }
        return boxes
    }

    /**
     * Landmark the raw camera Image (ZERO-COPY) — only called when
     * [boxes] is non-empty. Returns per-face landmark arrays (x, y pixels;
     * z scaled by width — Python parity) + blendshapes, paired to [boxes]
     * by nearest-center matching.
     */
    fun landmark(
        image: Image, imageW: Int, imageH: Int, timestampMs: Long,
        boxes: List<FaceBox>, scaleTo: FaceBox.() -> FaceBox = { this }
    ): List<FaceLandmarks> {
        if (boxes.isEmpty()) return emptyList()
        val mpImage = MediaImageBuilder(image).build()
        val result = try {
            getLandmarker().detectForVideo(mpImage, processingOpts(), timestampMs)
        } catch (t: Throwable) {
            Log.e(TAG, "landmark failed", t)
            return emptyList()
        }
        val rotated = rotationDegrees % 180 != 0
        val w = if (rotated) imageH else imageW
        val h = if (rotated) imageW else imageH

        class FaceData(var x: FloatArray, var y: FloatArray, var z: FloatArray,
                       var blendshapes: Map<String, Double>)

        val faces = ArrayList<FaceData>(result.faceLandmarks().size)
        for (lmList in result.faceLandmarks()) {
            val n = lmList.size
            val px = FloatArray(n); val py = FloatArray(n); val pz = FloatArray(n)
            for (i in 0 until n) {
                val lm = lmList[i]
                px[i] = lm.x() * w
                py[i] = lm.y() * h
                pz[i] = lm.z() * w   // Python: lm.z * width
            }
            faces.add(FaceData(px, py, pz, emptyMap()))
        }
        result.faceBlendshapes().ifPresent { blendLists ->
            for (i in faces.indices) {
                if (i < blendLists.size) {
                    val map = HashMap<String, Double>(blendLists[i].size)
                    for (bs: Category in blendLists[i]) {
                        map[bs.categoryName()] = bs.score().toDouble()
                    }
                    faces[i].blendshapes = map
                }
            }
        }
        if (faces.isEmpty()) return emptyList()

        val out = ArrayList<FaceLandmarks>(boxes.size)
        for (boxRaw in boxes) {
            val box = boxRaw.scaleTo()
            var best: FaceData? = null
            var bestDist = Double.MAX_VALUE
            for (f in faces) {
                val cx = f.x[1].toDouble()
                val cy = f.y[1].toDouble()
                val dx = cx - box.centerX
                val dy = cy - box.centerY
                val dist = kotlin.math.sqrt(dx * dx + dy * dy)
                if (dist < bestDist) { bestDist = dist; best = f }
            }
            val maxDist = maxOf(box.w, box.h) * 1.5
            out.add(
                if (bestDist < maxDist && best != null) {
                    FaceLandmarks(best!!.x, best!!.y, best!!.z, best!!.blendshapes, false)
                } else FaceLandmarks.estimatedFrom(box)
            )
        }
        return out
    }

    fun close() {
        try { detector?.close() } catch (_: Exception) {}
        try { stillDetector?.close() } catch (_: Exception) {}
        try { landmarker?.close() } catch (_: Exception) {}
        detector = null
        stillDetector = null
        landmarker = null
    }
}

/**
 * Per-face landmark data. `estimated` landmarks are synthesized from a bbox
 * (Python `_estimate_landmarks_from_box`) when the landmarker misses a face.
 */
data class FaceLandmarks(
    val x: FloatArray,
    val y: FloatArray,
    val z: FloatArray,
    val blendshapes: Map<String, Double> = emptyMap(),
    val estimated: Boolean = false
) {
    companion object {
        /** Python _estimate_landmarks_from_box: eye/pose keypoints from box fractions. */
        fun estimatedFrom(box: FaceBox): FaceLandmarks {
            val n = 478
            val x = FloatArray(n); val y = FloatArray(n); val z = FloatArray(n)
            val (bx, by, bw, bh) = listOf(box.x.toFloat(), box.y.toFloat(), box.w.toFloat(), box.h.toFloat())
            val leX = bx + (0.30f * bw); val reX = bx + (0.70f * bw); val eY = by + (0.35f * bh)
            fun put(idx: Int, fx: Float, fy: Float) { x[idx] = fx; y[idx] = fy; z[idx] = 0f }
            // Left eye: 362, 385, 387, 263, 373, 380
            put(362, leX - 0.05f * bw, eY)
            put(385, leX, eY - 0.02f * bh)
            put(387, leX + 0.03f * bw, eY - 0.02f * bh)
            put(263, leX + 0.05f * bw, eY)
            put(373, leX + 0.03f * bw, eY + 0.02f * bh)
            put(380, leX, eY + 0.02f * bh)
            // Right eye: 33, 160, 158, 133, 153, 144
            put(33, reX - 0.05f * bw, eY)
            put(160, reX - 0.03f * bw, eY - 0.02f * bh)
            put(158, reX, eY - 0.02f * bh)
            put(133, reX + 0.05f * bw, eY)
            put(153, reX, eY + 0.02f * bh)
            put(144, reX - 0.03f * bw, eY + 0.02f * bh)
            // Pose points
            put(1, bx + bw / 2f, by + 0.55f * bh)
            put(152, bx + bw / 2f, by + bh)
            put(287, bx + 0.2f * bw, by + 0.7f * bh)
            put(57, bx + 0.8f * bw, by + 0.7f * bh)
            return FaceLandmarks(x, y, z, estimated = true)
        }
    }
}