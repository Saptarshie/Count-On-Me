import cv2
import time
import numpy as np
from pathlib import Path
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

# Load BlazeFace
det_model = "models/blaze_face_short_range.tflite"
det_opts = mp_vision.FaceDetectorOptions(
    base_options=mp_python.BaseOptions(model_asset_path=det_model),
    min_detection_confidence=0.5
)
detector = mp_vision.FaceDetector.create_from_options(det_opts)

# Load FaceLandmarker
mesh_model = "models/face_landmarker.task"
mesh_opts = mp_vision.FaceLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=mesh_model),
    output_face_blendshapes=True,
    num_faces=5
)
landmarker = mp_vision.FaceLandmarker.create_from_options(mesh_opts)

# Test on a dummy image or real image
dummy = np.zeros((480, 640, 3), dtype=np.uint8)
mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=dummy)

t0 = time.time()
for _ in range(10):
    d_res = detector.detect(mp_img)
    m_res = landmarker.detect(mp_img)
elapsed = (time.time() - t0) / 10
print(f"Combined Detection + Landmarker latency: {elapsed*1000:.2f} ms ({1.0/elapsed:.1f} FPS)")
