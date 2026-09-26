import time
import numpy as np
import cv2
from app.detection import FaceDetector
from app.engagement import EngagementTracker
from app.recognition import FaceRecognizer
from app.database import DatabaseService

print("Initializing...")
db = DatabaseService()
detector = FaceDetector()
tracker = EngagementTracker()

print(f"detector use_mediapipe: {detector.use_mediapipe}")
print(f"tracker analyzer use_mediapipe: {tracker.analyzer.use_mediapipe}")

dummy = np.zeros((480, 640, 3), dtype=np.uint8)
# Draw a fake face circle
cv2.circle(dummy, (320, 240), 100, (200, 200, 200), -1)

# Time detector
t0 = time.time()
for _ in range(5):
    dets = detector.detect(dummy)
t_det = (time.time() - t0) / 5
print(f"Detector detect time: {t_det*1000:.1f}ms, dets: {len(dets)}")

# Time tracker
t0 = time.time()
for _ in range(5):
    res = tracker.track(dummy, detections=dets)
t_track = (time.time() - t0) / 5
print(f"Tracker track time: {t_track*1000:.1f}ms")

# Time db queries
t0 = time.time()
for _ in range(5):
    active_sess = db.sessions.get_active_session()
    sess_id = active_sess.session_id if active_sess else None
    db.attendance.get_attendance_count(session_id=sess_id)
t_db = (time.time() - t0) / 5
print(f"DB queries time: {t_db*1000:.1f}ms")
