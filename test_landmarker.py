import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# Test FaceLandmarker on a real image from dataset/Saptarshi/
import glob
images = glob.glob("dataset/Saptarshi/*.jpg")
if not images:
    images = glob.glob("unknown/*.jpg")

if images:
    test_img = cv2.imread(images[0])
    h, w = test_img.shape[:2]
    
    base_options = python.BaseOptions(model_asset_path='models/face_landmarker.task')
    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        output_face_blendshapes=True,
        num_faces=1
    )
    landmarker = vision.FaceLandmarker.create_from_options(options)
    
    rgb = cv2.cvtColor(test_img, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker.detect(mp_img)
    
    if result.face_landmarks:
        lms = result.face_landmarks[0]
        print(f"Detected {len(lms)} landmarks on real face!")
        
        # Test left eye EAR
        # 362, 385, 387, 263, 373, 380
        def pt(idx):
            lm = lms[idx]
            return np.array([lm.x * w, lm.y * h])
        
        v1 = np.linalg.norm(pt(385) - pt(373))
        v2 = np.linalg.norm(pt(387) - pt(380))
        h_dist = np.linalg.norm(pt(362) - pt(263))
        ear = (v1 + v2) / (2.0 * h_dist)
        print(f"Calculated Real Left Eye EAR: {ear:.4f}")
        
        # Check blendshapes
        if result.face_blendshapes:
            blendshapes = {b.category_name: b.score for b in result.face_blendshapes[0]}
            print(f"Blink Left blendshape: {blendshapes.get('eyeBlinkLeft', 0):.4f}")
            print(f"Blink Right blendshape: {blendshapes.get('eyeBlinkRight', 0):.4f}")
    else:
        print("No face landmarks detected in image")
else:
    print("No test images found")
