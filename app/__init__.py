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
    jsonify, redirect, url_for, flash, send_file
)
from datetime import datetime, date
from pathlib import Path
import threading
import time
import logging
import io

import sys
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from app.detection import FaceDetector, FaceDetection
from app.recognition import FaceRecognizer, DatasetEncoder
from app.engagement import EngagementTracker, EngagementStatus, StudentEngagementAnalyzer
from app.database import DatabaseService, Student, AttendanceRecord
from app.utils import (
    CameraStream, setup_logging, get_logger, FPSCounter,
    draw_text_with_background, DatasetCollector
)


# Initialize logging
logger = get_logger(__name__)

# Project root for templates and static files
PROJECT_ROOT = Path(__file__).parent.parent

# Initialize Flask app
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / 'templates'),
    static_folder=str(PROJECT_ROOT / 'static')
)
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
                
                # Process frame
                processed = self._process_frame(frame)
                
                with self._lock:
                    self.processed_frame = processed
                
                # Update FPS
                self.fps_counter.tick()
                
            except Exception as e:
                logger.error(f"Processing error: {e}")
                time.sleep(0.1)
    
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
            
            # Extract face for recognition
            face_img = self.detector.extract_face(frame, det)
            
            if face_img is not None:
                # Recognize face
                result = self.recognizer.recognize(face_img)
                
                # Get engagement for this face
                engagement = None
                if idx < len(engagement_results):
                    _, engagement = engagement_results[idx]
                
                # Draw bounding box with color based on recognition
                if result.is_known:
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
                if engagement and result.is_known:
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


# ============================================================================
# Routes - Pages
# ============================================================================

@app.route('/')
def index():
    """Dashboard home page."""
    stats = state.db_service.get_dashboard_stats() if state.db_service else {}
    return render_template('index.html', stats=stats)


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
