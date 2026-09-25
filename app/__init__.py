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
import time
import logging
import io
import shutil

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from app.detection import FaceDetector, FaceDetection
from app.recognition import FaceRecognizer, DatasetEncoder, TemporalVotingRecognizer
from app.engagement import EngagementTracker, EngagementStatus, StudentEngagementAnalyzer
from app.database import DatabaseService, Student, AttendanceRecord
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
        
        self._lock = threading.Lock()
        self._processing_thread = None
        self._stop_event = threading.Event()
    
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
        
        self.is_running = False
    
    def _start_processing(self):
        """Start the background processing thread."""
        self._stop_event.clear()
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            daemon=True
        )
        self._processing_thread.start()
    
    def _stop_processing(self):
        """Stop the background processing thread."""
        self._stop_event.set()
        if self._processing_thread:
            self._processing_thread.join(timeout=2.0)
    
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
                processed = self._process_frame(frame)
                
                with self._lock:
                    self.processed_frame = processed
                
                # Update FPS
                self.fps_counter.tick()
                
            except Exception as e:
                logger.error(f"Processing error: {e}")
                time.sleep(0.1)
    
    def _update_adaptive_stride(self):
        """
        Select processing stride from current FPS:
            FPS > 20 -> every 3rd frame
            FPS 10-20 -> every 2nd frame
            FPS < 10 -> every frame
        This is an explicit accuracy-vs-latency tradeoff: skip only when
        the pipeline has spare capacity.
        """
        fps = self.fps_counter.get_fps()
        if fps > config.detection.adaptive_high_fps:
            new_stride = config.detection.stride_high
        elif fps > config.detection.adaptive_low_fps:
            new_stride = config.detection.stride_mid
        else:
            new_stride = config.detection.stride_low
        
        if new_stride != self._adaptive_stride:
            logger.debug(f"Adaptive stride: {self._adaptive_stride} -> {new_stride} "
                          f"(FPS {fps:.1f})")
            self._adaptive_stride = new_stride
    
    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """Process a single frame."""
        output = frame.copy()
        height, width = frame.shape[:2]
        
        # Detect faces
        detections = self.detector.detect(frame)
        
        # Get engagement data
        engagement_results = self.engagement_tracker.track(frame)
        
        # Process each detection
        for idx, det in enumerate(detections):
            x, y, w, h = det.bbox
            
            # Stable track key: spatially-bucketed centroid (simple tracker)
            cx, cy = det.center
            track_key = f"t{cx // 80}_{cy // 80}"
            
            # Extract face for recognition
            face_img = self.detector.extract_face(frame, det)
            
            if face_img is not None:
                # Recognize face
                result = self.recognizer.recognize(face_img)
                
                # ------------------------------------------------------
                # TEMPORAL VOTING: aggregate observations per track and
                # accept identity only on majority agreement.
                # ------------------------------------------------------
                if config.temporal.enabled:
                    accepted_name = self.temporal_recognizer.observe(
                        track_key, result.name, result.confidence
                    )
                    if accepted_name is None:
                        # Not enough votes yet -> treat as unidentified
                        is_known = False
                    else:
                        is_known = True
                        result.name = accepted_name
                else:
                    is_known = result.is_known
                
                # ------------------------------------------------------
                # UNKNOWN FACE QUEUE: save crops of unidentified faces
                # for teacher review / later registration.
                # ------------------------------------------------------
                if not is_known:
                    self._save_unknown_face(frame, det, track_key, result.confidence)
                
                # Get engagement for this face
                engagement = None
                if idx < len(engagement_results):
                    _, engagement = engagement_results[idx]
                
                # Draw bounding box with color based on recognition
                if is_known:
                    color = (0, 255, 0)  # Green for known
                    name = result.name
                    
                    # Mark attendance
                    if self.recognizer.can_mark_attendance(name):
                        eng_score = engagement.engagement_score if engagement else 0
                        success, msg = self.db_service.attendance.mark_attendance(
                            name, eng_score
                        )
                        if success:
                            self.recognizer.mark_attendance_logged(name)
                            logger.info(f"Attendance marked for {name}")
                    
                    # Update student engagement
                    if engagement:
                        self.student_analyzer.update_student(name, engagement)
                        self.tracked_students[name] = engagement
                        
                        # Update engagement score in database
                        self.db_service.attendance.update_engagement_score(
                            name, engagement.engagement_score
                        )
                else:
                    color = (0, 0, 255)  # Red for unknown
                    name = "Unknown"
                
                # Draw rectangle
                cv2.rectangle(output, (x, y), (x + w, y + h), color, 2)
                
                # Draw name and confidence
                label = f"{name} ({result.confidence:.2f})"
                output = draw_text_with_background(
                    output, label, (x, y - 10),
                    color=(255, 255, 255), bg_color=color
                )
                
                # Draw engagement if available
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
        
        # Draw FPS
        fps = self.fps_counter.get_fps()
        cv2.putText(
            output, f"FPS: {fps:.1f}", (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
        )
        
        # Draw attendance count
        count = self.db_service.attendance.get_attendance_count()
        cv2.putText(
            output, f"Present: {count}", (10, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
        )
        
        return output
    
    def get_processed_frame(self) -> np.ndarray:
        """Get the latest processed frame."""
        with self._lock:
            if self.processed_frame is not None:
                return self.processed_frame.copy()
        return None
    
    def _save_unknown_face(self, frame: np.ndarray, det: FaceDetection,
                           track_key: str, similarity: float):
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
            
            x, y, w, h = det.bbox
            pad = int(min(w, h) * 0.2)
            crop = frame[max(0, y - pad): y + h + pad,
                         max(0, x - pad): x + w + pad]
            if crop.size == 0:
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
            # Return a placeholder frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(
                frame, "Camera not started", (200, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2
            )
        
        # Encode to JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
        
        frame_bytes = buffer.tobytes()
        
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n'
        )
        
        time.sleep(0.033)  # ~30 FPS


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
    """Get current system statistics."""
    if not state.db_service:
        return jsonify({'error': 'System not initialized'}), 500
    
    stats = state.db_service.get_dashboard_stats()
    stats['is_running'] = state.is_running
    stats['fps'] = state.fps_counter.get_fps()
    stats['tracked_students'] = len(state.tracked_students)
    
    return jsonify(stats)


@app.route('/api/attendance', methods=['GET'])
def api_get_attendance():
    """Get attendance records."""
    date_str = request.args.get('date', date.today().isoformat())
    
    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        check_date = date.today()
    
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    
    records = state.db_service.attendance.get_attendance_by_date(check_date)
    
    return jsonify({
        'date': check_date.isoformat(),
        'records': [
            {
                'id': r.id,
                'name': r.student_name,
                'time': r.time,
                'engagement_score': r.engagement_score,
                'status': r.status
            }
            for r in records
        ]
    })


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
    """Export attendance to CSV."""
    if not state.db_service:
        return jsonify({'error': 'Database not initialized'}), 500
    
    # Create CSV in memory
    output = io.StringIO()
    
    from datetime import date
    import csv
    
    records = state.db_service.attendance.get_attendance_by_date(date.today())
    
    writer = csv.writer(output)
    writer.writerow(['Name', 'Date', 'Time', 'Engagement Score', 'Status'])
    
    for r in records:
        writer.writerow([r.student_name, r.date, r.time, r.engagement_score, r.status])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=attendance_{date.today()}.csv'}
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


@app.route('/api/unknown-faces', methods=['GET'])
def api_unknown_faces():
    """List unknown faces saved in the review queue."""
    out_dir = Path(config.unknown_queue.dir)
    entries = []
    if out_dir.exists():
        for f in sorted(out_dir.glob("*.jpg"), reverse=True):
            entries.append({
                'filename': f.name,
                'url': f'/unknown/{f.name}',
                'created': datetime.fromtimestamp(f.stat().st_mtime).isoformat()
            })
    return jsonify({'unknown_faces': entries, 'count': len(entries)})


@app.route('/unknown/<path:filename>')
def unknown_face_image(filename):
    """Serve an unknown-face crop image."""
    out_dir = Path(config.unknown_queue.dir)
    return send_from_directory(str(out_dir), filename)


@app.route('/api/unknown-faces/register', methods=['POST'])
def api_register_unknown():
    """
    Register an unknown face crop as a new student.
    Copies the crop into the dataset and adds its encoding.
    """
    data = request.json
    if not data or 'filename' not in data or 'name' not in data:
        return jsonify({'error': 'filename and name are required'}), 400
    
    try:
        src = Path(config.unknown_queue.dir) / data['filename']
        if not src.exists():
            return jsonify({'error': 'File not found'}), 404
        
        name = data['name'].strip()
        student_dir = Path(config.recognition.dataset_path) / name
        student_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy into dataset (kept for future re-encoding)
        dst = student_dir / f"unknown_{src.stem}.jpg"
        shutil.copy2(str(src), str(dst))
        
        # Encode this face and add to the live recognizer
        image = cv2.imread(str(dst))
        ok = state.recognizer.add_new_student(name, [image]) if image is not None else False
        
        if ok:
            src.unlink()  # remove from queue
            return jsonify({'status': 'success', 'message': f'Registered {name}'})
        return jsonify({'error': 'No face found in crop'}), 400
        
    except Exception as e:
        logger.error(f"Register unknown failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/unknown-faces/ignore', methods=['POST'])
def api_ignore_unknown():
    """Remove an unknown-face crop from the review queue."""
    data = request.json
    if not data or 'filename' not in data:
        return jsonify({'error': 'filename is required'}), 400
    
    try:
        src = Path(config.unknown_queue.dir) / data['filename']
        if src.exists():
            src.unlink()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
