"""
Flask Application for Real-Time Attendance and Engagement System.

This module provides the web interface and API endpoints for:
- Live video streaming with face detection
- Attendance marking and viewing
- Engagement analytics dashboard
- Student management
- Data export

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
from flask import (
    Flask, render_template, Response, request, 
    jsonify, redirect, url_for, flash, send_file,
    send_from_directory
)
from datetime import datetime, date
from pathlib import Path
import threading
import queue
import time
import logging
import io
import shutil
import json
from typing import Dict, Tuple, Optional, List, Any

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from app.detection import FaceDetector, FaceDetection
from app.recognition import FaceRecognizer, DatasetEncoder, TemporalVotingRecognizer, RecognitionResult
from app.engagement import (
    EngagementTracker, EngagementStatus, StudentEngagementAnalyzer,
    EngagementMetrics, EyeMetrics, HeadPose
)
from app.database import DatabaseService, Student, AttendanceRecord, Session
from app.utils import (
    CameraStream, setup_logging, get_logger, FPSCounter,
    draw_text_with_background, DatasetCollector
)
from app.batch import BatchAttendanceProcessor


# Initialize logging
logger = get_logger(__name__)

from flask_cors import CORS

# Project root for templates and static files
PROJECT_ROOT = Path(__file__).parent.parent

# Initialize Flask app
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / 'templates'),
    static_folder=str(PROJECT_ROOT / 'static')
)
CORS(app, resources={r"/*": {"origins": "*"}})
app.secret_key = config.flask.secret_key
app.config['MAX_CONTENT_LENGTH'] = config.flask.max_content_length


# ============================================================================
# Global State Manager
# ============================================================================

class SystemState:
    """
    Global state manager for the attendance system.
    
    Manages camera, detectors, recognizers, and tracking state.
    """
    
    def __init__(self):
        self.camera: CameraStream = None
        self.detector: FaceDetector = None
        self.recognizer: FaceRecognizer = None
        self.engagement_tracker: EngagementTracker = None
        self.student_analyzer: StudentEngagementAnalyzer = None
        self.db_service: DatabaseService = None
        
        self.is_running = False
        self.is_processing = False
        self.current_frame = None
        self.processed_frame = None
        
        self.tracked_students = {}  # name -> last engagement metrics
        self.fps_counter = FPSCounter()
        
        # Adaptive frame skipping state
        self._frame_counter = 0
        self._adaptive_stride = config.detection.frame_skip
        
        # Temporal voting recognizer (per-face-track vote history)
        self.temporal_recognizer = TemporalVotingRecognizer()
        
        # Unknown face queue (cropped faces saved for teacher review)
        self._unknown_last_saved: dict = {}  # track_key -> datetime
        
        # Recognition queue and background batch worker
        self._recog_queue = queue.Queue(maxsize=32)
        self._recog_thread = None
        
        # Spatial track cache: track_id -> track dict
        self._tracks: Dict[int, dict] = {}
        self._next_track_id = 1
        self._track_lock = threading.Lock()
        self._student_last_seen: Dict[str, float] = {}
        
        self._lock = threading.Lock()
        self._processing_thread = None
        self._stop_event = threading.Event()
        
        # Database query caching & throttling for high-FPS streaming
        self._last_active_session = None
        self._last_session_check_time = 0.0
        self._cached_attendance_count = 0
        self._last_count_check_time = 0.0
        self._last_db_score_update: Dict[str, float] = {}
    
    def initialize(self):
        """Initialize all system components."""
        logger.info("Initializing system components...")
        
        try:
            # Initialize database
            self.db_service = DatabaseService()
            
            # Initialize detectors
            self.detector = FaceDetector()
            self.recognizer = FaceRecognizer()
            self.engagement_tracker = EngagementTracker()
            self.student_analyzer = StudentEngagementAnalyzer()
            
            logger.info("System components initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error initializing system: {e}")
            return False
    
    def start_camera(self) -> bool:
        """Start the camera stream."""
        if self.camera and self.camera.is_opened():
            return True
        
        self.camera = CameraStream()
        success = self.camera.start()
        
        if success:
            self.is_running = True
            self._start_processing()
        
        return success
    
    def stop_camera(self):
        """Stop the camera stream."""
        self._stop_processing()
        
        if self.camera:
            self.camera.stop()
            self.camera = None
        
        with self._track_lock:
            self._tracks.clear()
            self._student_last_seen.clear()
            self.tracked_students.clear()
            
        while not self._recog_queue.empty():
            try:
                self._recog_queue.get_nowait()
                self._recog_queue.task_done()
            except Exception:
                break
        
        self.is_running = False
    
    def _start_processing(self):
        """Start background processing and recognition threads."""
        self._stop_event.clear()
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            daemon=True
        )
        self._processing_thread.start()
        
        self._recog_thread = threading.Thread(
            target=self._recognition_worker,
            daemon=True
        )
        self._recog_thread.start()
    
    def _stop_processing(self):
        """Stop background processing and recognition threads."""
        self._stop_event.set()
        if self._processing_thread:
            self._processing_thread.join(timeout=2.0)
        if self._recog_thread:
            self._recog_thread.join(timeout=2.0)
    
    def _processing_loop(self):
        """Main processing loop for face detection, recognition, and engagement."""
        while not self._stop_event.is_set():
            try:
                if not self.camera or not self.camera.is_opened():
                    time.sleep(0.1)
                    continue
                
                # Get frame
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    continue
                
                self.current_frame = frame.copy()
                
                # ----------------------------------------------------------
                # ADAPTIVE FRAME SKIPPING
                # Stride adapts to measured FPS: high FPS lets us skip more
                # frames (latency budget), low FPS forces full processing.
                # ----------------------------------------------------------
                self._frame_counter += 1
                if config.detection.adaptive_skip_enabled:
                    self._update_adaptive_stride()
                if self._frame_counter % max(1, self._adaptive_stride) != 0:
                    continue
                
                # Process frame
                try:
                    processed = self._process_frame(frame)
                except Exception as e:
                    logger.error(f"Processing error in frame: {e}")
                    processed = frame.copy()
                
                with self._lock:
                    self.processed_frame = processed
                
                # Update FPS
                self.fps_counter.tick()
                
            except Exception as e:
                logger.error(f"Camera loop error: {e}")
                time.sleep(0.1)
    
    def _update_adaptive_stride(self):
        """
        Adjust frame skipping based on processing capacity.
        If FPS drops below adaptive_low_fps, skip frames to relieve CPU.
        """
        fps = self.fps_counter.get_fps()
        if not config.detection.adaptive_skip_enabled:
            self._adaptive_stride = max(1, config.detection.frame_skip)
            return
            
        if fps < config.detection.adaptive_low_fps:
            new_stride = config.detection.stride_mid
        else:
            new_stride = 1
        
        if new_stride != self._adaptive_stride:
            self._adaptive_stride = new_stride

    def _recognition_worker(self):
        """
        Background worker that continuously pulls face crops from the queue,
        batches them into a single tensor, and runs vectorized face recognition.
        This completely decouples heavy deep learning inference from the real-time
        video streaming loop.
        """
        logger.info("Face recognition background worker started.")
        while not self._stop_event.is_set():
            try:
                try:
                    first_item = self._recog_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                batch = [first_item]
                max_batch = getattr(config.recognition, 'batch_size', 4)
                while len(batch) < max_batch:
                    try:
                        batch.append(self._recog_queue.get_nowait())
                    except queue.Empty:
                        break

                track_ids = [item[0] for item in batch]
                face_imgs = [item[1] for item in batch]

                # Batched DeepFace inference (vectorized cosine similarity)
                results = self.recognizer.recognize_batch(face_imgs)

                now = time.time()
                for tid, res, img in zip(track_ids, results, face_imgs):
                    track_key = f"t_{tid}"
                    if config.temporal.enabled:
                        accepted_name = self.temporal_recognizer.observe(
                            track_key, res.name, res.confidence
                        )
                        if accepted_name is None:
                            is_known = False
                        else:
                            is_known = True
                            res.name = accepted_name
                    else:
                        is_known = res.is_known

                    if not is_known:
                        self._save_unknown_face(img, track_key, res.confidence)

                    with self._track_lock:
                        if tid in self._tracks:
                            self._tracks[tid]["result"] = res
                            self._tracks[tid]["is_known"] = is_known
                            self._tracks[tid]["in_flight"] = False
                            self._tracks[tid]["last_recog"] = now

                for _ in batch:
                    self._recog_queue.task_done()

            except Exception as e:
                logger.error(f"Recognition worker error: {e}", exc_info=True)
                time.sleep(0.05)
    
    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Process a single frame with 25-30 FPS real-time performance:
        1. MediaPipe Face Detection (fast, ~10ms)
        2. Configurable False-Positive Noise Filter (ignores tiny non-face artifacts)
        3. MediaPipe Engagement Tracking (fast, ~8ms)
        4. Spatial Track Association with Cached Recognition (instant, <1ms)
        5. Asynchronous enqueue for stale/new tracks without blocking the preview stream.
        """
        output = frame.copy()
        height, width = frame.shape[:2]
        
        # 1. Detect faces
        detections = self.detector.detect(frame)
        
        # 2. Configurable False-Positive Noise Filter
        min_size = getattr(config.detection, 'min_face_size', 55)
        valid_detections = [
            d for d in detections 
            if d.bbox[2] >= min_size and d.bbox[3] >= min_size
        ]
        
        # 3. Fast Engagement Tracking
        engagement_results = self.engagement_tracker.track(frame, detections=valid_detections)
        
        # 4. Spatial Track Association
        now = time.time()
        ttl = getattr(config.recognition, 'cache_ttl_seconds', 3.0)
        
        with self._track_lock:
            # Expire tracks not seen for > 3.0s
            dead_tids = [
                tid for tid, trk in self._tracks.items()
                if (now - trk["last_seen"]) > 3.0
            ]
            for tid in dead_tids:
                del self._tracks[tid]
            
            matched_tids = set()
            det_to_track = []
            
            for det in valid_detections:
                cx, cy = det.center
                best_tid = None
                best_dist = 110.0  # Max pixel movement between frames for same face
                
                for tid, trk in self._tracks.items():
                    if tid in matched_tids:
                        continue
                    tcx, tcy = trk["center"]
                    dist = ((cx - tcx)**2 + (cy - tcy)**2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_tid = tid
                
                if best_tid is not None:
                    matched_tids.add(best_tid)
                    trk = self._tracks[best_tid]
                    trk["center"] = (cx, cy)
                    trk["bbox"] = det.bbox
                    trk["last_seen"] = now
                    det_to_track.append(best_tid)
                else:
                    new_tid = self._next_track_id
                    self._next_track_id += 1
                    self._tracks[new_tid] = {
                        "track_id": new_tid,
                        "center": (cx, cy),
                        "bbox": det.bbox,
                        "last_seen": now,
                        "last_recog": 0.0,
                        "result": RecognitionResult(name="Identifying...", confidence=0.0, distance=1.0, is_known=False),
                        "is_known": False,
                        "in_flight": False
                    }
                    matched_tids.add(new_tid)
                    det_to_track.append(new_tid)
        
        # 5. Non-blocking Async Recognition Queue
        for det, tid in zip(valid_detections, det_to_track):
            with self._track_lock:
                trk = self._tracks.get(tid)
                if not trk:
                    continue
                should_recog = (now - trk["last_recog"] > ttl) and not trk["in_flight"]
                if should_recog:
                    trk["in_flight"] = True
                    trk["last_recog"] = now
            
            if should_recog:
                face_img = self.detector.extract_face(frame, det)
                if face_img is not None and face_img.size > 0:
                    try:
                        self._recog_queue.put_nowait((tid, face_img.copy()))
                    except queue.Full:
                        with self._track_lock:
                            if tid in self._tracks:
                                self._tracks[tid]["in_flight"] = False

        # 6. Render Overlays Immediately (Zero Latency)
        # Fetch active session with 2.0s caching to eliminate per-frame SQLite disk locks
        if (now - self._last_session_check_time) > 2.0 or self._last_active_session is None:
            try:
                self._last_active_session = self.db_service.sessions.get_active_session()
                self._last_session_check_time = now
            except Exception as e:
                logger.debug(f"Session query error: {e}")
        active_sess = self._last_active_session
        active_sess_id = active_sess.session_id if active_sess else None

        active_seen_names = set()
        for idx, (det, tid) in enumerate(zip(valid_detections, det_to_track)):
            x, y, w, h = det.bbox
            with self._track_lock:
                trk = self._tracks.get(tid)
                if trk:
                    result = trk["result"]
                    is_known = trk["is_known"]
                else:
                    result = RecognitionResult(name="Unknown", confidence=0.0, distance=1.0, is_known=False)
                    is_known = False

            engagement = None
            if idx < len(engagement_results):
                _, engagement = engagement_results[idx]
            if engagement is None:
                engagement = EngagementMetrics(
                    head_pose=HeadPose(yaw=0.0, pitch=0.0, roll=0.0),
                    eye_metrics=EyeMetrics(average_ear=0.28, left_ear=0.28, right_ear=0.28),
                    blink_rate=16.0,
                    engagement_score=85.0,
                    status=EngagementStatus.ATTENTIVE
                )

            if is_known:
                color = (0, 255, 0)
                name = result.name
                active_seen_names.add(name)
                self._student_last_seen[name] = now

                if self.recognizer.can_mark_attendance(name):
                    eng_score = engagement.engagement_score if engagement else 85.0
                    success, msg = self.db_service.attendance.mark_attendance(
                        name, eng_score, session_id=active_sess_id
                    )
                    if success:
                        self.recognizer.mark_attendance_logged(name)
                        logger.info(f"Attendance marked for {name} in session {active_sess_id}")

                if engagement:
                    self.student_analyzer.update_student(name, engagement)
                    self.tracked_students[name] = engagement
                    # Throttle engagement DB write to at most once per 3.0 seconds per student
                    last_up = self._last_db_score_update.get(name, 0.0)
                    if now - last_up > 3.0:
                        self._last_db_score_update[name] = now
                        self.db_service.attendance.update_engagement_score(
                            name, engagement.engagement_score, session_id=active_sess_id
                        )
            else:
                color = (0, 0, 255)
                name = result.name

            cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)

            conf_str = f" ({result.confidence:.2f})" if result.confidence > 0 else ""
            label = f"{name}{conf_str}"
            output = draw_text_with_background(
                output, label, (x, y - 10),
                color=(255, 255, 255), bg_color=color
            )

            if engagement and is_known:
                status_color = {
                    EngagementStatus.ATTENTIVE: (0, 255, 0),
                    EngagementStatus.DISTRACTED: (0, 165, 255),
                    EngagementStatus.SLEEPING: (0, 0, 255),
                }.get(engagement.status, (128, 128, 128))

                eng_label = f"{engagement.status.value}: {engagement.engagement_score:.0f}%"
                output = draw_text_with_background(
                    output, eng_label, (x, y + h + 20),
                    color=(255, 255, 255), bg_color=status_color
                )

        # Remove tracked students that have left the camera view (>4.0s)
        for sname in list(self.tracked_students.keys()):
            if now - self._student_last_seen.get(sname, 0.0) > 4.0:
                self.tracked_students.pop(sname, None)

        # Draw FPS
        fps = self.fps_counter.get_fps()
        cv2.putText(
            output, f"FPS: {fps:.1f}", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
        )

        # Draw attendance count (cached every 2.0s)
        if (now - self._last_count_check_time) > 2.0:
            try:
                self._cached_attendance_count = self.db_service.attendance.get_attendance_count(session_id=active_sess_id)
                self._last_count_check_time = now
            except Exception as e:
                logger.debug(f"Error drawing count: {e}")

        cv2.putText(
            output, f"Present: {self._cached_attendance_count}", (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
        )

        return output
    
    def get_processed_frame(self) -> np.ndarray:
        """Get the latest processed frame, fallback to current raw camera frame."""
        with self._lock:
            if self.processed_frame is not None:
                return self.processed_frame.copy()
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None
    
    def _save_unknown_face(self, crop: np.ndarray, track_key: str, similarity: float):
        """
        Save a cropped unknown face to the review queue.
        Applies a per-track cooldown so one lingering stranger doesn't
        flood the queue with hundreds of near-identical crops.
        """
        try:
            if similarity < config.unknown_queue.min_confidence:
                return
            now = datetime.now()
            last = self._unknown_last_saved.get(track_key)
            if last and (now - last).total_seconds() < config.unknown_queue.cooldown_seconds:
                return
            
            if crop is None or crop.size == 0:
                return
            
            out_dir = Path(config.unknown_queue.dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            
            # Enforce max queue size (oldest first)
            entries = sorted(out_dir.glob("*.jpg"))
            while len(entries) >= config.unknown_queue.max_entries:
                entries[0].unlink()
                entries = entries[1:]
            
            filename = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{track_key}.jpg"
            cv2.imwrite(str(out_dir / filename), crop)
            self._unknown_last_saved[track_key] = now
            logger.info(f"Unknown face saved: {filename}")
        except Exception as e:
            logger.error(f"Failed to save unknown face: {e}")
    
    def cleanup(self):
        """Cleanup all resources."""
        self.stop_camera()
        
        if self.detector:
            self.detector.release()
        if self.engagement_tracker:
            self.engagement_tracker.release()
        
        logger.info("System cleanup complete")


# Global state instance
state = SystemState()


# ============================================================================
# Video Streaming
# ============================================================================

def generate_video_stream():
    """Generate video stream for MJPEG streaming."""
    while True:
        frame = state.get_processed_frame()
        
        if frame is None:
            # Return an informative placeholder frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            msg = "Camera starting..." if state.is_running else "Camera stopped"
            submsg = "AI models warming up" if state.is_running else "Click Start in Dashboard or Live Camera"
            cv2.putText(
                frame, msg, (190, 230),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
            )
            cv2.putText(
                frame, submsg, (150, 270),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 140, 140), 1
            )
        
        # Encode to JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            time.sleep(0.02)
            continue
        
        frame_bytes = buffer.tobytes()
        
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n'
        )
        
        time.sleep(0.04)  # ~25 FPS


FRONTEND_DIST = PROJECT_ROOT / 'frontend' / 'dist'

@app.route('/')
def index():
    """Dashboard home page: serves React SPA if built, else fallback template."""
    if (FRONTEND_DIST / 'index.html').exists():
        return send_from_directory(str(FRONTEND_DIST), 'index.html')
    stats = state.db_service.get_dashboard_stats() if state.db_service else {}
    return render_template('index.html', stats=stats)


@app.route('/assets/<path:filename>')
def spa_assets(filename):
    """Serve built React frontend static assets."""
    assets_dir = FRONTEND_DIST / 'assets'
    if assets_dir.exists():
        return send_from_directory(str(assets_dir), filename)
    return ('Not found', 404)


@app.route('/live')
def live():
    """Live video feed page."""
    return render_template('live.html')


@app.route('/attendance')
def attendance():
    """Attendance records page."""
    date_str = request.args.get('date', date.today().isoformat())
    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        check_date = date.today()
    
    records = []
    if state.db_service:
        records = state.db_service.attendance.get_attendance_by_date(check_date)
    
    return render_template('attendance.html', records=records, selected_date=check_date)


@app.route('/students')
def students():
    """Student management page."""
    student_list = []
    if state.db_service:
        student_list = state.db_service.students.get_all_students()
    
    return render_template('students.html', students=student_list)


@app.route('/analytics')
def analytics():
    """Analytics dashboard page."""
    stats = {}
    student_engagement = {}
    
    if state.db_service:
        stats = state.db_service.get_dashboard_stats()
        if state.student_analyzer:
            student_engagement = state.student_analyzer.get_all_student_stats()
    
    return render_template('analytics.html', stats=stats, engagement=student_engagement)


@app.route('/register')
def register():
    """Student registration page."""
    return render_template('register.html')


# ============================================================================
# Routes - API
# ============================================================================

@app.route('/video_feed')
def video_feed():
    """Video streaming endpoint."""
    return Response(
        generate_video_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/api/stream/events')
def api_stream_events():
    """
    Server-Sent Events (SSE) telemetry stream.
    Pushes real-time FPS, camera status, active session, tracked students engagement,
    and attendee counts directly to connected clients without HTTP polling.
    """
    def event_stream():
        last_db_time = 0.0
        cached_active_sess = None
        cached_present_count = 0
        cached_avg_eng = 0.0
        cached_total = 0
        cached_absent = 0
        cached_pct = 0.0

        while True:
            try:
                now_t = time.time()
                if (now_t - last_db_time) > 1.5 and state.db_service:
                    try:
                        cached_active_sess = state.db_service.sessions.get_active_session()
                        sess_id = cached_active_sess.session_id if cached_active_sess else None
                        cached_present_count = state.db_service.attendance.get_attendance_count(session_id=sess_id)
                        cached_avg_eng = state.db_service.attendance.get_average_engagement(session_id=sess_id)
                        cached_total = state.db_service.students.get_student_count()
                        cached_absent = max(0, cached_total - cached_present_count)
                        cached_pct = (cached_present_count / cached_total * 100) if cached_total > 0 else 0.0
                        last_db_time = now_t
                    except Exception as e:
                        logger.debug(f"SSE DB query error: {e}")

                tracked = {}
                for name, metrics in list(state.tracked_students.items()):
                    tracked[name] = metrics.to_dict()
                
                payload = {
                    'is_running': state.is_running,
                    'fps': round(state.fps_counter.get_fps(), 1),
                    'active_session': cached_active_sess.to_dict() if cached_active_sess else None,
                    'active_session_id': cached_active_sess.session_id if cached_active_sess else None,
                    'present_count': cached_present_count,
                    'total_students': cached_total,
                    'absent_count': cached_absent,
                    'attendance_percentage': round(cached_pct, 1),
                    'average_engagement': round(cached_avg_eng, 1),
                    'tracked_students': tracked,
                    'timestamp': datetime.now().isoformat()
                }
                
                yield f"data: {json.dumps(payload)}\n\n"
            except (GeneratorExit, StopIteration):
                break
            except Exception as e:
                logger.debug(f"SSE stream error: {e}")
                
            time.sleep(0.5)

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*'
        }
    )


@app.route('/api/start', methods=['POST'])
def api_start():
    """Start the attendance system."""
    if state.is_running:
        return jsonify({'status': 'already_running'})
    
    if not state.detector:
        state.initialize()
    
    success = state.start_camera()
    
    if success:
        return jsonify({'status': 'started'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to start camera'}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop():
    """Stop the attendance system."""
    state.stop_camera()
    return jsonify({'status': 'stopped'})


@app.route('/api/stats')
def api_stats():
    """Get current system statistics, optionally scoped to a session."""
    if not state.db_service:
        return jsonify({'error': 'System not initialized'}), 500
    
    session_id = request.args.get('session_id')
    stats = state.db_service.get_dashboard_stats(session_id=session_id)
    stats['is_running'] = state.is_running
    stats['fps'] = state.fps_counter.get_fps()
    stats['tracked_students'] = {name: m.to_dict() for name, m in list(state.tracked_students.items())}
    stats['tracked_students_count'] = len(state.tracked_students)
    
    return jsonify(stats)


@app.route('/api/sessions', methods=['GET'])
def api_get_sessions():
    """Get classroom sessions for a date (or all sessions)."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    date_str = request.args.get('date')
    if date_str:
        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            sessions = state.db_service.sessions.get_sessions_by_date(check_date)
        except ValueError:
            sessions = state.db_service.sessions.get_all_sessions()
    else:
        sessions = state.db_service.sessions.get_all_sessions()
        
    active = state.db_service.sessions.get_active_session()
    return jsonify({
        'sessions': [s.to_dict() for s in sessions],
        'active_session_id': active.session_id if active else None,
        'active_session': active.to_dict() if active else None
    })


@app.route('/api/sessions', methods=['POST'])
def api_create_session():
    """Create a new classroom session."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    data = request.get_json(silent=True) or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({'error': 'Session title is required'}), 400
        
    date_str = data.get('date')
    if date_str:
        try:
            sess_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            sess_date = date.today()
    else:
        sess_date = date.today()
        
    session = Session(
        title=title,
        course=data.get('course') or title,
        date=sess_date,
        start_time=data.get('start_time') or datetime.now().strftime('%H:%M'),
        end_time=data.get('end_time') or '',
        room=data.get('room') or 'Room 101',
        is_active=bool(data.get('set_active', True))
    )
    
    created = state.db_service.sessions.create_session(session)
    if created.is_active and state.recognizer:
        state.recognizer.clear_attendance_log()
        
    return jsonify({'status': 'success', 'session': created.to_dict()})


@app.route('/api/sessions/active', methods=['GET'])
def api_get_active_session():
    """Get the currently active session."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    active = state.db_service.sessions.get_active_session()
    return jsonify({'active_session': active.to_dict() if active else None})


@app.route('/api/sessions/active', methods=['POST'])
def api_set_active_session():
    """Set the active session for live camera attendance."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    if not session_id:
        return jsonify({'error': 'session_id is required'}), 400
        
    success = state.db_service.sessions.set_active_session(session_id)
    if success and state.recognizer:
        state.recognizer.clear_attendance_log()
        
    active = state.db_service.sessions.get_session(session_id)
    return jsonify({
        'status': 'success' if success else 'not_found',
        'active_session': active.to_dict() if active else None
    })


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def api_delete_session(session_id):
    """Delete a session and all its attendance records."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    success = state.db_service.sessions.delete_session(session_id)
    if success and state.recognizer:
        state.recognizer.clear_attendance_log()
        
    active = state.db_service.sessions.get_active_session()
    return jsonify({
        'status': 'success' if success else 'not_found',
        'active_session': active.to_dict() if active else None
    })


@app.route('/api/attendance', methods=['GET'])
def api_get_attendance():
    """Get attendance records, optionally filtered by session_id or date."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    session_id = request.args.get('session_id')
    date_str = request.args.get('date')
    
    if session_id:
        records = state.db_service.attendance.get_attendance_by_session(session_id)
        session_info = state.db_service.sessions.get_session(session_id)
        return jsonify({
            'session_id': session_id,
            'session': session_info.to_dict() if session_info else None,
            'records': [r.to_dict() for r in records]
        })
        
    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        check_date = date.today()
        
    records = state.db_service.attendance.get_attendance_by_date(check_date)
    return jsonify({
        'date': check_date.isoformat(),
        'records': [r.to_dict() for r in records]
    })


@app.route('/api/attendance/<int:record_id>', methods=['PUT', 'PATCH'])
def api_update_attendance_status(record_id):
    """Manually correct student attendance status or engagement score."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if not status:
        return jsonify({'error': 'status is required'}), 400
        
    score = data.get('engagement_score')
    if score is not None:
        try:
            score = float(score)
        except ValueError:
            score = None
            
    success = state.db_service.attendance.update_attendance_status(record_id, status, score)
    return jsonify({
        'status': 'success' if success else 'not_found',
        'message': f'Updated attendance record #{record_id} to {status}'
    })


@app.route('/api/attendance/manual', methods=['POST'])
def api_manual_mark_student():
    """Manually add or mark student attendance in a session."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    data = request.get_json(silent=True) or {}
    session_id = data.get('session_id')
    student_name = data.get('student_name', '').strip()
    status = data.get('status', 'Present')
    score = float(data.get('engagement_score', 100.0))
    
    if not student_name:
        return jsonify({'error': 'student_name is required'}), 400
        
    if not session_id:
        active = state.db_service.sessions.get_active_session()
        session_id = active.session_id if active else None
        
    if not session_id:
        return jsonify({'error': 'No active session found'}), 400
        
    success, msg = state.db_service.attendance.manual_mark_student(session_id, student_name, status, score)
    return jsonify({'status': 'success' if success else 'error', 'message': msg})


@app.route('/api/attendance/<int:record_id>', methods=['DELETE'])
def api_delete_attendance(record_id):
    """Delete a single attendance record."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
        
    success = state.db_service.attendance.delete_attendance(record_id)
    return jsonify({'status': 'success' if success else 'not_found'})


@app.route('/api/engagement')
def api_engagement():
    """Get real-time engagement data."""
    engagement_data = {}
    
    for name, metrics in state.tracked_students.items():
        engagement_data[name] = metrics.to_dict()
    
    return jsonify(engagement_data)


@app.route('/api/students', methods=['GET'])
def api_get_students():
    """Get all students."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    
    students = state.db_service.students.get_all_students()
    
    return jsonify({
        'students': [
            {
                'id': s.id,
                'student_id': s.student_id,
                'name': s.name,
                'email': s.email,
                'department': s.department
            }
            for s in students
        ]
    })


@app.route('/api/students', methods=['POST'])
def api_add_student():
    """Add a new student."""
    data = request.json
    
    if not data or 'name' not in data:
        return jsonify({'error': 'Name is required'}), 400
    
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    
    student = Student(
        student_id=data.get('student_id', data['name'].lower().replace(' ', '_')),
        name=data['name'],
        email=data.get('email'),
        department=data.get('department')
    )
    
    try:
        row_id = state.db_service.students.add_student(student)
        return jsonify({'status': 'success', 'id': row_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/students/<student_id>', methods=['DELETE'])
def api_delete_student(student_id):
    """Delete a student by student_id."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    try:
        success = state.db_service.students.delete_student(student_id, soft_delete=False)
        return jsonify({'status': 'success' if success else 'not_found'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/encode', methods=['POST'])
def api_encode_dataset():
    """Encode/re-encode the face dataset."""
    try:
        encoder = DatasetEncoder()
        encoder.encode_dataset()
        success = encoder.save_encodings()
        
        if success:
            # Reload recognizer
            if state.recognizer:
                state.recognizer.reload_encodings()
            
            return jsonify({'status': 'success', 'message': 'Dataset encoded successfully'})
        else:
            return jsonify({'error': 'Failed to save encodings'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export/csv')
def api_export_csv():
    """Export attendance to CSV with session support."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    
    session_id = request.args.get('session_id')
    date_str = request.args.get('date')
    
    output = io.StringIO()
    import csv
    writer = csv.writer(output)
    writer.writerow(['Student Name', 'Session ID', 'Session Title', 'Course', 'Date', 'Time', 'Engagement Score (%)', 'Status'])
    
    filename = f"attendance_{date.today()}.csv"
    if session_id:
        records = state.db_service.attendance.get_attendance_by_session(session_id)
        session_info = state.db_service.sessions.get_session(session_id)
        if session_info:
            clean_name = f"{session_info.course}_{session_info.title}".replace(' ', '_').replace('/', '_')
            filename = f"attendance_{clean_name}_{session_info.date}.csv"
        else:
            filename = f"attendance_{session_id}.csv"
    else:
        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
        except (ValueError, TypeError):
            check_date = date.today()
        records = state.db_service.attendance.get_attendance_by_date(check_date)
        filename = f"attendance_{check_date}.csv"
    
    for r in records:
        writer.writerow([
            r.student_name,
            r.session_id or '',
            getattr(r, 'session_title', '') or '',
            getattr(r, 'course', '') or '',
            r.date,
            r.time,
            f"{r.engagement_score:.1f}",
            r.status
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@app.route('/exports/<path:filename>')
def exported_file(filename):
    """Serve exported CSV reports."""
    return send_from_directory(str(config.batch.export_dir), filename)


@app.route('/api/batch-attendance', methods=['POST'])
def api_batch_attendance():
    """
    Multi-image attendance with cross-image face deduplication.

    Accepts JSON: {"folder": "<path to folder of classroom images>"}
    Runs detection -> embeddings -> deduplication -> unique attendance,
    marks identified students present, and exports a CSV report.
    """
    data = request.json
    if not data or 'folder' not in data:
        return jsonify({'error': 'folder is required'}), 400
    
    folder = Path(data['folder'])
    if not folder.exists() or not folder.is_dir():
        return jsonify({'error': f'Folder not found: {folder}'}), 400
    
    if not state.detector or not state.recognizer:
        state.initialize()
    
    try:
        processor = BatchAttendanceProcessor(
            detector=state.detector, recognizer=state.recognizer
        )
        report = processor.process_folder(folder)
        
        if 'error' in report:
            return jsonify(report), 400
        
        csv_path = processor.export_csv(report=report)
        report['csv'] = csv_path
        
        logger.info(
            f"Batch attendance: {report['images_processed']} images, "
            f"{report['faces_detected']} faces, "
            f"{report['unique_people']} unique, "
            f"{report['duplicates_removed']} duplicates removed"
        )
        return jsonify(report)
        
    except Exception as e:
        logger.error(f"Batch attendance failed: {e}")
        return jsonify({'error': str(e)}), 500


# In-memory cache for unknown face embeddings: filename -> (mtime, embedding_vector)
_unknown_face_embeddings_cache: Dict[str, Tuple[float, Optional[np.ndarray]]] = {}


def _cluster_unknown_faces(similarity_threshold: float = 0.58):
    """
    Cluster unknown face images by embedding cosine similarity.
    Returns:
        tuple: (clusters, unclustered_entries)
    """
    out_dir = Path(config.unknown_queue.dir)
    if not out_dir.exists():
        return [], []

    files = sorted(out_dir.glob("*.jpg"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return [], []

    if not state.recognizer:
        state.initialize()

    encoder = state.recognizer.encoder

    embeddings = []
    valid_entries = []
    unclassified_entries = []

    for f in files:
        mtime = f.stat().st_mtime
        entry = {
            'filename': f.name,
            'url': f'/unknown/{f.name}',
            'created': datetime.fromtimestamp(mtime).isoformat()
        }

        # Check cache
        cached = _unknown_face_embeddings_cache.get(f.name)
        if cached and cached[0] == mtime:
            emb = cached[1]
        else:
            try:
                img = cv2.imread(str(f))
                if img is not None:
                    encs = encoder.encode_face(img)
                    emb = encs[0] if encs else None
                else:
                    emb = None
            except Exception as e:
                logger.debug(f"Failed to encode {f.name}: {e}")
                emb = None
            _unknown_face_embeddings_cache[f.name] = (mtime, emb)

        if emb is not None:
            embeddings.append(emb)
            valid_entries.append(entry)
        else:
            unclassified_entries.append(entry)

    if not embeddings:
        if unclassified_entries:
            return [{
                'cluster_id': 'cluster_unclassified',
                'representative': unclassified_entries[0]['filename'],
                'representative_url': unclassified_entries[0]['url'],
                'count': len(unclassified_entries),
                'faces': unclassified_entries,
                'is_unclassified': True
            }], unclassified_entries
        return [], []

    # Compute cosine similarity matrix
    M = np.array(embeddings)
    norms = np.linalg.norm(M, axis=1, keepdims=True) + 1e-10
    M_norm = M / norms
    sim_matrix = M_norm @ M_norm.T

    visited = set()
    clusters = []

    for i in range(len(valid_entries)):
        if i in visited:
            continue
        cluster_indices = [i]
        visited.add(i)
        for j in range(i + 1, len(valid_entries)):
            if j not in visited and sim_matrix[i, j] >= similarity_threshold:
                cluster_indices.append(j)
                visited.add(j)

        cluster_faces = [valid_entries[idx] for idx in cluster_indices]
        cluster_id = f"cluster_{len(clusters) + 1}"
        for cf in cluster_faces:
            cf['cluster_id'] = cluster_id

        clusters.append({
            'cluster_id': cluster_id,
            'representative': cluster_faces[0]['filename'],
            'representative_url': cluster_faces[0]['url'],
            'count': len(cluster_faces),
            'faces': cluster_faces
        })

    # Add unclassified / low quality crops as an extra cluster if any
    if unclassified_entries:
        for uf in unclassified_entries:
            uf['cluster_id'] = 'cluster_misc'
        clusters.append({
            'cluster_id': 'cluster_misc',
            'representative': unclassified_entries[0]['filename'],
            'representative_url': unclassified_entries[0]['url'],
            'count': len(unclassified_entries),
            'faces': unclassified_entries,
            'is_unclassified': True
        })

    clusters.sort(key=lambda c: c['count'], reverse=True)
    return clusters, unclassified_entries


@app.route('/api/unknown-faces', methods=['GET'])
def api_unknown_faces():
    """List unknown faces saved in the review queue, optionally clustered."""
    out_dir = Path(config.unknown_queue.dir)
    entries = []
    if out_dir.exists():
        for f in sorted(out_dir.glob("*.jpg"), key=lambda x: x.stat().st_mtime, reverse=True):
            entries.append({
                'filename': f.name,
                'url': f'/unknown/{f.name}',
                'created': datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            })

    clusters = []
    if request.args.get('cluster') == 'true' and entries:
        try:
            clusters, _ = _cluster_unknown_faces()
            cluster_map = {}
            for c in clusters:
                for fc in c.get('faces', []):
                    cluster_map[fc['filename']] = c['cluster_id']
            for e in entries:
                e['cluster_id'] = cluster_map.get(e['filename'])
        except Exception as e:
            logger.error(f"Clusterify on get failed: {e}")

    return jsonify({'unknown_faces': entries, 'count': len(entries), 'clusters': clusters})


@app.route('/api/unknown-faces/clusterify', methods=['POST'])
def api_clusterify_unknown():
    """Cluster all pending unknown faces by facial similarity."""
    try:
        clusters, unclassified = _cluster_unknown_faces()
        out_dir = Path(config.unknown_queue.dir)
        total_count = len(list(out_dir.glob("*.jpg"))) if out_dir.exists() else 0
        return jsonify({
            'status': 'success',
            'count': total_count,
            'clusters': clusters,
            'unclassified_count': len(unclassified)
        })
    except Exception as e:
        logger.error(f"Clusterify failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/unknown-faces/clear', methods=['POST', 'DELETE'])
@app.route('/api/unknown-faces', methods=['DELETE'])
def api_clear_unknown_queue():
    """Purge all unknown face captures from the review queue."""
    out_dir = Path(config.unknown_queue.dir)
    cleared = 0
    if out_dir.exists():
        for f in out_dir.glob("*.jpg"):
            try:
                f.unlink()
                cleared += 1
            except Exception:
                pass
    _unknown_face_embeddings_cache.clear()
    logger.info(f"Cleared {cleared} images from unknown faces review queue")
    return jsonify({'status': 'success', 'cleared': cleared})


@app.route('/unknown/<path:filename>')
def unknown_face_image(filename):
    """Serve an unknown-face crop image."""
    out_dir = Path(config.unknown_queue.dir)
    return send_from_directory(str(out_dir), filename)


@app.route('/api/unknown-faces/register', methods=['POST'])
@app.route('/api/unknown-faces/register-cluster', methods=['POST'])
def api_register_unknown():
    """
    Register one or more unknown face crops as an enrolled student.
    Saves approved images to dataset/<name>/, creates Student record in DB,
    encodes faces into live recognizer, and removes them from the queue.
    """
    data = request.json
    if not data or 'name' not in data or not data.get('name', '').strip():
        return jsonify({'error': 'Student name is required'}), 400
    
    filenames = data.get('filenames')
    if not filenames and 'filename' in data:
        filenames = [data['filename']]
    
    if not filenames:
        return jsonify({'error': 'At least one face image filename is required'}), 400

    name = data['name'].strip()
    student_id = data.get('student_id', '').strip() or f"STU_{name.upper().replace(' ', '_')}"
    department = data.get('department', 'Computer Science').strip()
    email = data.get('email', '').strip() or None

    if not state.db_service:
        state.initialize()

    out_dir = Path(config.unknown_queue.dir)
    student_dir = Path(config.recognition.dataset_path) / name
    student_dir.mkdir(parents=True, exist_ok=True)

    loaded_images = []
    saved_paths = []
    files_to_unlink = []

    try:
        # 1. Add student to database
        student = Student(
            student_id=student_id,
            name=name,
            email=email,
            department=department
        )
        try:
            state.db_service.students.add_student(student)
        except Exception as e:
            logger.warning(f"DB add_student: {e}")

        # 2. Process all specified filenames
        for fn in filenames:
            src = out_dir / fn
            if src.exists():
                dst = student_dir / f"cluster_{src.name}"
                shutil.copy2(str(src), str(dst))
                saved_paths.append(dst)
                files_to_unlink.append(src)
                
                img = cv2.imread(str(dst))
                if img is not None:
                    loaded_images.append(img)

        if not loaded_images:
            return jsonify({'error': 'No readable images found from selected filenames'}), 400

        # 3. Add to live recognizer (immediate encoding)
        ok = state.recognizer.add_new_student(name, loaded_images) if state.recognizer else False

        # 4. Remove successfully registered files from unknown queue
        for f in files_to_unlink:
            try:
                f.unlink()
                _unknown_face_embeddings_cache.pop(f.name, None)
            except Exception:
                pass

        logger.info(f"Registered {name} ({student_id}) with {len(loaded_images)} images (encoded: {ok})")
        return jsonify({
            'status': 'success',
            'message': f"Registered {name} with {len(loaded_images)} photos!",
            'encoded': ok,
            'count': len(loaded_images)
        })

    except Exception as e:
        logger.error(f"Register unknown failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/unknown-faces/ignore', methods=['POST'])
def api_ignore_unknown():
    """Remove one or more unknown-face crops from the review queue."""
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    filenames = data.get('filenames')
    if not filenames and 'filename' in data:
        filenames = [data['filename']]

    if not filenames:
        return jsonify({'error': 'filename or filenames required'}), 400

    out_dir = Path(config.unknown_queue.dir)
    removed = 0
    for fn in filenames:
        src = out_dir / fn
        if src.exists():
            try:
                src.unlink()
                _unknown_face_embeddings_cache.pop(fn, None)
                removed += 1
            except Exception:
                pass

    return jsonify({'status': 'success', 'removed': removed})


@app.route('/api/register-student', methods=['POST'])
def api_register_student():
    """
    Full student registration: DB record + face images + live encoding.

    Accepts JSON:
        {name, student_id?, email?, department?,
         images: ["data:image/jpeg;base64,...", ...]}

    Saves images to dataset/<name>/, adds the DB record, and encodes
    the faces into the live recognizer immediately (no manual re-encode
    step required).
    """
    data = request.json
    if not data or 'name' not in data or not data.get('name', '').strip():
        return jsonify({'error': 'Name is required'}), 400
    if not data.get('images'):
        return jsonify({'error': 'At least one face image is required'}), 400
    
    name = data['name'].strip()
    images_b64 = data['images']
    
    if not state.db_service:
        state.initialize()
    
    try:
        # Decode base64 images (strip data-URL prefix if present)
        import base64, re
        images = []
        for b64 in images_b64:
            try:
                if ',' in b64 and b64.strip().startswith('data:'):
                    b64 = b64.split(',', 1)[1]
                img_bytes = base64.b64decode(b64)
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is not None:
                    images.append(img)
            except Exception:
                continue
        
        if not images:
            return jsonify({'error': 'No valid face images received'}), 400
        
        # 1. Add student to database
        student = Student(
            student_id=data.get('student_id') or name.lower().replace(' ', '_'),
            name=name,
            email=data.get('email'),
            department=data.get('department')
        )
        try:
            state.db_service.students.add_student(student)
        except Exception as e:
            # Duplicate DB record is not fatal - face data still matters
            logger.warning(f"DB add_student: {e}")
        
        # 2. Save images to dataset folder (source of truth for re-encoding)
        student_dir = Path(config.recognition.dataset_path) / name
        student_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime as _dt
        timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
        saved = 0
        for i, img in enumerate(images):
            path = student_dir / f"web_{timestamp}_{i:02d}.jpg"
            if cv2.imwrite(str(path), img):
                saved += 1
        logger.info(f"Saved {saved}/{len(images)} images to {student_dir}")
        
        # 3. Encode faces and add to the live recognizer
        encoded = state.recognizer.add_new_student(name, images) if state.recognizer else False
        
        return jsonify({
            'status': 'success',
            'message': f'Registered {name}: {saved} images saved, '
                       f'{"face encoded" if encoded else "encoding failed - run Re-encode"}'
        })
        
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/tuning', methods=['GET', 'POST'])
def api_tuning():
    """
    Get or update detection & recognition tuning parameters at runtime.
    Allows configuring the False-Positive Noise Filter (min_face_size),
    detection confidence, recognition distance threshold, and caching TTL.
    """
    if request.method == 'GET':
        return jsonify({
            'success': True,
            'min_face_size': getattr(config.detection, 'min_face_size', 55),
            'min_detection_confidence': int(config.detection.min_detection_confidence * 100),
            'recognition_threshold': int(config.recognition.recognition_threshold * 100),
            'batch_size': getattr(config.recognition, 'batch_size', 4),
            'cache_ttl_seconds': getattr(config.recognition, 'cache_ttl_seconds', 3.0),
            'adaptive_skip_enabled': config.detection.adaptive_skip_enabled
        })

    data = request.get_json(silent=True) or {}
    
    if 'min_face_size' in data:
        try:
            val = int(data['min_face_size'])
            if 10 <= val <= 400:
                config.detection.min_face_size = val
                logger.info(f"Updated False-Positive Noise Filter: min_face_size = {val}px")
        except (ValueError, TypeError):
            pass

    if 'min_detection_confidence' in data:
        try:
            val = float(data['min_detection_confidence'])
            conf = val / 100.0 if val > 1.0 else val
            if 0.1 <= conf <= 0.99:
                config.detection.min_detection_confidence = conf
                if state.detector:
                    state.detector.min_detection_confidence = conf
                logger.info(f"Updated min_detection_confidence = {conf:.2f}")
        except (ValueError, TypeError):
            pass

    if 'recognition_threshold' in data:
        try:
            val = float(data['recognition_threshold'])
            thresh = val / 100.0 if val > 1.0 else val
            if 0.1 <= thresh <= 1.0:
                config.recognition.recognition_threshold = thresh
                if state.recognizer:
                    state.recognizer.recognition_threshold = thresh
                logger.info(f"Updated recognition_threshold = {thresh:.2f}")
        except (ValueError, TypeError):
            pass

    if 'cache_ttl_seconds' in data:
        try:
            val = float(data['cache_ttl_seconds'])
            if 0.5 <= val <= 30.0:
                config.recognition.cache_ttl_seconds = val
        except (ValueError, TypeError):
            pass

    return jsonify({
        'success': True,
        'message': 'Tuning settings updated',
        'min_face_size': config.detection.min_face_size,
        'min_detection_confidence': int(config.detection.min_detection_confidence * 100),
        'recognition_threshold': int(config.recognition.recognition_threshold * 100),
        'cache_ttl_seconds': config.recognition.cache_ttl_seconds
    })


# ============================================================================
# Error Handlers
# ============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors."""
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors."""
    logger.error(f"Server error: {e}")
    return render_template('error.html', error='Internal server error'), 500


# ============================================================================
# App Lifecycle
# ============================================================================

@app.before_request
def before_request():
    """Initialize state before first request."""
    if not state.db_service:
        state.initialize()


def cleanup():
    """Cleanup on shutdown."""
    state.cleanup()


import atexit
atexit.register(cleanup)


# ============================================================================
# Main Entry Point (for direct run)
# ============================================================================

if __name__ == '__main__':
    state.initialize()
    app.run(
        host=config.flask.host,
        port=config.flask.port,
        debug=config.flask.debug,
        threaded=True
    )
