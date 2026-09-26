"""
Engagement Tracking Module using MediaPipe FaceMesh.

This module provides student engagement analysis through:
- Eye Aspect Ratio (EAR) for drowsiness/sleep detection
- Head Pose Estimation for attention direction
- Blink frequency analysis
- Composite engagement scoring

Features:
- Real-time 468 facial landmark detection
- Drowsiness detection
- Attention tracking
- Engagement categorization (Attentive/Distracted/Sleeping)

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from enum import Enum
from collections import deque
from datetime import datetime, timedelta
import logging
import math

# MediaPipe support: Try Tasks API first (MediaPipe >= 0.10.x / 1.0+), then legacy solutions
MEDIAPIPE_TASKS_AVAILABLE = False
MEDIAPIPE_AVAILABLE = False
mp = None
mp_python = None
mp_vision = None

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    MEDIAPIPE_TASKS_AVAILABLE = True
except (ImportError, AttributeError):
    pass

try:
    if mp is not None and hasattr(mp, 'solutions') and hasattr(mp.solutions, 'face_mesh'):
        MEDIAPIPE_AVAILABLE = True
except Exception:
    pass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config

FACE_LANDMARKER_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "face_landmarker.task"



# Configure module logger
logger = logging.getLogger(__name__)


class EngagementStatus(Enum):
    """Engagement status categories."""
    ATTENTIVE = "Attentive"
    DISTRACTED = "Distracted"
    SLEEPING = "Sleeping"
    UNKNOWN = "Unknown"


@dataclass
class HeadPose:
    """Data class for head pose angles."""
    
    yaw: float = 0.0    # Left/right rotation
    pitch: float = 0.0  # Up/down rotation
    roll: float = 0.0   # Tilt
    
    @property
    def is_looking_forward(self) -> bool:
        """Check if head is facing forward."""
        return (
            abs(self.yaw) < config.engagement.yaw_threshold and
            abs(self.pitch) < config.engagement.pitch_threshold and
            abs(self.roll) < config.engagement.roll_threshold
        )
    
    def get_attention_score(self) -> float:
        """Calculate attention score based on head pose (0-100)."""
        yaw_score = max(0, 100 - (abs(self.yaw) / config.engagement.yaw_threshold * 100))
        pitch_score = max(0, 100 - (abs(self.pitch) / config.engagement.pitch_threshold * 100))
        roll_score = max(0, 100 - (abs(self.roll) / config.engagement.roll_threshold * 100))
        
        return (yaw_score + pitch_score + roll_score) / 3


@dataclass
class EyeMetrics:
    """Data class for eye-related metrics."""
    
    left_ear: float = 0.0
    right_ear: float = 0.0
    average_ear: float = 0.0
    is_blinking: bool = False
    eyes_closed_frames: int = 0
    
    @property
    def is_drowsy(self) -> bool:
        """Check if person is drowsy based on EAR."""
        return self.average_ear < config.engagement.ear_threshold
    
    @property
    def is_sleeping(self) -> bool:
        """Check if person is sleeping (prolonged eye closure)."""
        return self.eyes_closed_frames > config.engagement.ear_consecutive_frames


@dataclass
class EngagementMetrics:
    """Data class for comprehensive engagement metrics."""
    
    head_pose: HeadPose = field(default_factory=HeadPose)
    eye_metrics: EyeMetrics = field(default_factory=EyeMetrics)
    blink_rate: float = 0.0  # Blinks per minute
    engagement_score: float = 0.0
    status: EngagementStatus = EngagementStatus.UNKNOWN
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        score_val = round(float(self.engagement_score), 1)
        ear_val = round(float(self.eye_metrics.average_ear), 2)
        return {
            'head_pose': {
                'yaw': self.head_pose.yaw,
                'pitch': self.head_pose.pitch,
                'roll': self.head_pose.roll
            },
            'eye_metrics': {
                'left_ear': self.eye_metrics.left_ear,
                'right_ear': self.eye_metrics.right_ear,
                'average_ear': self.eye_metrics.average_ear,
                'is_blinking': self.eye_metrics.is_blinking
            },
            'score': score_val,
            'engagement_score': score_val,
            'ear': ear_val,
            'average_ear': ear_val,
            'blink_rate': round(float(self.blink_rate), 1),
            'is_blinking': bool(self.eye_metrics.is_blinking),
            'is_attentive': self.status == EngagementStatus.ATTENTIVE,
            'is_sleeping': self.status == EngagementStatus.SLEEPING,
            'status': self.status.value,
            'timestamp': self.timestamp.isoformat()
        }


class FaceMeshAnalyzer:
    """
    FaceMesh Analyzer using MediaPipe for facial landmark detection.
    
    Provides 468 facial landmarks for detailed face analysis including
    eye tracking, head pose estimation, and engagement metrics.
    Falls back to OpenCV when MediaPipe is unavailable.
    """
    
    # Landmark indices for eyes (MediaPipe FaceMesh)
    LEFT_EYE_INDICES = [362, 385, 387, 263, 373, 380]
    RIGHT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    
    # Landmark indices for head pose estimation
    FACE_OVAL_INDICES = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
                         397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
                         172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
    
    # Key points for pose estimation
    NOSE_TIP = 1
    CHIN = 152
    LEFT_EYE_CORNER = 263
    RIGHT_EYE_CORNER = 33
    LEFT_MOUTH_CORNER = 287
    RIGHT_MOUTH_CORNER = 57
    
    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        max_faces: int = 20
    ):
        """
        Initialize FaceMesh analyzer.
        
        Args:
            min_detection_confidence: Minimum detection confidence
            min_tracking_confidence: Minimum tracking confidence
            max_faces: Maximum number of faces to track
        """
        self.use_mediapipe = False
        self._task_landmarker = None
        self.face_mesh = None
        self.mp_face_mesh = None
        self.mp_drawing = None
        self.mp_drawing_styles = None
        self._face_cascade = None
        
        # 1. Try modern MediaPipe Tasks FaceLandmarker (high speed ~13ms, with blendshapes)
        if MEDIAPIPE_TASKS_AVAILABLE and FACE_LANDMARKER_MODEL_PATH.exists():
            try:
                base_options = mp_python.BaseOptions(model_asset_path=str(FACE_LANDMARKER_MODEL_PATH))
                options = mp_vision.FaceLandmarkerOptions(
                    base_options=base_options,
                    output_face_blendshapes=True,
                    num_faces=max_faces
                )
                if hasattr(mp_vision, 'FaceLandmarker'):
                    try:
                        mp_vision.FaceLandmarker.__del__ = lambda self: None
                    except Exception:
                        pass
                self._task_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
                self.use_mediapipe = True
                logger.info("Using MediaPipe Tasks FaceLandmarker for high-speed engagement tracking")
            except Exception as e:
                logger.warning(f"MediaPipe Tasks FaceLandmarker init failed: {e}")
                self._task_landmarker = None

        # 2. Fall back to legacy MediaPipe solutions.face_mesh if available
        if not self.use_mediapipe and MEDIAPIPE_AVAILABLE:
            try:
                self.mp_face_mesh = mp.solutions.face_mesh
                self.mp_drawing = mp.solutions.drawing_utils
                self.mp_drawing_styles = mp.solutions.drawing_styles
                
                self.face_mesh = self.mp_face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=max_faces,
                    refine_landmarks=True,
                    min_detection_confidence=min_detection_confidence,
                    min_tracking_confidence=min_tracking_confidence
                )
                self.use_mediapipe = True
                logger.info("Using legacy MediaPipe FaceMesh for engagement tracking")
            except Exception as e:
                logger.warning(f"Legacy MediaPipe FaceMesh init failed: {e}")
        
        # 3. OpenCV fallback if MediaPipe is completely unavailable
        if not self.use_mediapipe:
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            logger.info("Using OpenCV fallback for engagement (limited features)")
        
        # Camera matrix for head pose (initialized on first frame)
        self._camera_matrix = None
        self._dist_coeffs = np.zeros((4, 1))
        
        logger.info(f"FaceMeshAnalyzer initialized for {max_faces} faces")
    
    def _init_camera_matrix(self, width: int, height: int):
        """Initialize camera matrix based on frame dimensions."""
        focal_length = width
        center = (width / 2, height / 2)
        self._camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)
    
    def process(self, frame: np.ndarray) -> List[Dict]:
        """
        Process frame and extract facial landmarks.
        
        Args:
            frame: BGR image
        
        Returns:
            List of landmark dictionaries for each detected face
        """
        try:
            height, width = frame.shape[:2]
            
            if self._camera_matrix is None:
                self._init_camera_matrix(width, height)
            
            faces_data = []
            
            if self._task_landmarker is not None:
                # Modern MediaPipe Tasks FaceLandmarker
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                result = self._task_landmarker.detect(mp_img)
                
                if result.face_landmarks:
                    for i, face_lms in enumerate(result.face_landmarks):
                        landmarks = {}
                        xs = []
                        ys = []
                        for idx, lm in enumerate(face_lms):
                            px = int(lm.x * width)
                            py = int(lm.y * height)
                            landmarks[idx] = (px, py, lm.z * width)
                            xs.append(px)
                            ys.append(py)
                        landmarks['estimated'] = False
                        
                        min_x, max_x = max(0, min(xs)), min(width, max(xs))
                        min_y, max_y = max(0, min(ys)), min(height, max(ys))
                        center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
                        bbox = (min_x, min_y, max_x - min_x, max_y - min_y)
                        
                        blendshapes = {}
                        if result.face_blendshapes and i < len(result.face_blendshapes):
                            blendshapes = {b.category_name: b.score for b in result.face_blendshapes[i]}
                        
                        faces_data.append({
                            'landmarks': landmarks,
                            'raw_landmarks': face_lms,
                            'center': center,
                            'bbox': bbox,
                            'blendshapes': blendshapes,
                            'estimated': False
                        })
            elif self.use_mediapipe and self.face_mesh is not None:
                # Legacy MediaPipe FaceMesh
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.face_mesh.process(rgb_frame)
                
                if results.multi_face_landmarks:
                    for face_landmarks in results.multi_face_landmarks:
                        landmarks = {}
                        xs = []
                        ys = []
                        for idx, lm in enumerate(face_landmarks.landmark):
                            px = int(lm.x * width)
                            py = int(lm.y * height)
                            landmarks[idx] = (px, py, lm.z * width)
                            xs.append(px)
                            ys.append(py)
                        landmarks['estimated'] = False
                        
                        min_x, max_x = max(0, min(xs)), min(width, max(xs))
                        min_y, max_y = max(0, min(ys)), min(height, max(ys))
                        center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
                        bbox = (min_x, min_y, max_x - min_x, max_y - min_y)
                        
                        faces_data.append({
                            'landmarks': landmarks,
                            'raw_landmarks': face_landmarks,
                            'center': center,
                            'bbox': bbox,
                            'blendshapes': {},
                            'estimated': False
                        })
            elif self._face_cascade is not None:
                # OpenCV fallback - provide estimated landmarks from face detection
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
                )
                
                for (x, y, w, h) in faces:
                    landmarks = self._estimate_landmarks_from_box(x, y, w, h)
                    center = (x + w / 2.0, y + h / 2.0)
                    faces_data.append({
                        'landmarks': landmarks,
                        'raw_landmarks': None,
                        'center': center,
                        'bbox': (x, y, w, h),
                        'blendshapes': {},
                        'estimated': True
                    })
            
            return faces_data
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return []
    
    def _estimate_landmarks_from_box(self, x: int, y: int, w: int, h: int) -> Dict:
        """
        Estimate basic facial landmarks from bounding box.
        Used as fallback when MediaPipe is unavailable.
        """
        landmarks = {}
        
        # Eyes (approximate positions)
        left_eye_x = x + int(0.3 * w)
        right_eye_x = x + int(0.7 * w)
        eye_y = y + int(0.35 * h)
        
        # Left eye landmarks
        landmarks[362] = (left_eye_x - int(0.05 * w), eye_y, 0)
        landmarks[385] = (left_eye_x, eye_y - int(0.02 * h), 0)
        landmarks[387] = (left_eye_x + int(0.03 * w), eye_y - int(0.02 * h), 0)
        landmarks[263] = (left_eye_x + int(0.05 * w), eye_y, 0)
        landmarks[373] = (left_eye_x + int(0.03 * w), eye_y + int(0.02 * h), 0)
        landmarks[380] = (left_eye_x, eye_y + int(0.02 * h), 0)
        
        # Right eye landmarks
        landmarks[33] = (right_eye_x - int(0.05 * w), eye_y, 0)
        landmarks[160] = (right_eye_x - int(0.03 * w), eye_y - int(0.02 * h), 0)
        landmarks[158] = (right_eye_x, eye_y - int(0.02 * h), 0)
        landmarks[133] = (right_eye_x + int(0.05 * w), eye_y, 0)
        landmarks[153] = (right_eye_x, eye_y + int(0.02 * h), 0)
        landmarks[144] = (right_eye_x - int(0.03 * w), eye_y + int(0.02 * h), 0)
        
        # Face pose landmarks
        landmarks[1] = (x + w // 2, y + int(0.55 * h), 0)  # Nose tip
        landmarks[152] = (x + w // 2, y + h, 0)  # Chin
        landmarks[287] = (x + int(0.2 * w), y + int(0.7 * h), 0)  # Left mouth
        landmarks[57] = (x + int(0.8 * w), y + int(0.7 * h), 0)  # Right mouth
        landmarks['estimated'] = True
        return landmarks
    
    def calculate_ear(self, landmarks: Dict) -> Tuple[float, float]:
        """
        Calculate Eye Aspect Ratio for both eyes.
        
        EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)
        
        Args:
            landmarks: Dictionary of landmark coordinates
        
        Returns:
            Tuple of (left_ear, right_ear)
        """
        if landmarks.get('estimated'):
            return 0.28, 0.28

        def eye_aspect_ratio(eye_indices: List[int]) -> float:
            try:
                # Get eye points
                points = [landmarks[idx][:2] for idx in eye_indices]
                
                # Vertical distances
                v1 = np.linalg.norm(np.array(points[1]) - np.array(points[5]))
                v2 = np.linalg.norm(np.array(points[2]) - np.array(points[4]))
                
                # Horizontal distance
                h = np.linalg.norm(np.array(points[0]) - np.array(points[3]))
                
                if h < 1e-6:
                    return 0.28
                
                ear = float((v1 + v2) / (2.0 * h))
                return ear
                
            except Exception:
                return 0.28
        
        left_ear = eye_aspect_ratio(self.LEFT_EYE_INDICES)
        right_ear = eye_aspect_ratio(self.RIGHT_EYE_INDICES)
        
        return left_ear, right_ear
    
    def estimate_head_pose(self, landmarks: Dict) -> HeadPose:
        """
        Estimate head pose (yaw, pitch, roll) from landmarks.
        
        Args:
            landmarks: Dictionary of landmark coordinates
        
        Returns:
            HeadPose object with angles in degrees
        """
        if landmarks.get('estimated'):
            return HeadPose(yaw=0.0, pitch=0.0, roll=0.0)

        try:
            # 3D model points (standard face model)
            model_points = np.array([
                (0.0, 0.0, 0.0),          # Nose tip
                (0.0, -330.0, -65.0),     # Chin
                (-225.0, 170.0, -135.0),  # Left eye corner
                (225.0, 170.0, -135.0),   # Right eye corner
                (-150.0, -150.0, -125.0), # Left mouth corner
                (150.0, -150.0, -125.0)   # Right mouth corner
            ], dtype=np.float64)
            
            # 2D image points
            image_points = np.array([
                landmarks[self.NOSE_TIP][:2],
                landmarks[self.CHIN][:2],
                landmarks[self.LEFT_EYE_CORNER][:2],
                landmarks[self.RIGHT_EYE_CORNER][:2],
                landmarks[self.LEFT_MOUTH_CORNER][:2],
                landmarks[self.RIGHT_MOUTH_CORNER][:2]
            ], dtype=np.float64)
            
            # Solve PnP
            success, rotation_vector, translation_vector = cv2.solvePnP(
                model_points,
                image_points,
                self._camera_matrix,
                self._dist_coeffs,
                flags=cv2.SOLVEPNP_ITERATIVE
            )
            
            if not success:
                return HeadPose()
            
            # Convert rotation vector to rotation matrix
            rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
            
            # Get Euler angles
            proj_matrix = np.hstack((rotation_matrix, translation_vector))
            _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(proj_matrix)
            
            pitch = float(euler_angles[0][0])
            yaw = float(euler_angles[1][0])
            roll = float(euler_angles[2][0])
            
            # Normalize roll (compensate for image Y-inversion where roll is centered around +/-180)
            if abs(roll) > 90:
                roll = (180.0 - abs(roll)) * (1.0 if roll > 0 else -1.0)
            
            # Offset pitch to center looking forward at webcam around 0
            pitch = pitch - 22.0
            
            return HeadPose(yaw=yaw, pitch=pitch, roll=roll)
            
        except Exception as e:
            logger.debug(f"Error estimating head pose: {e}")
            return HeadPose()
    
    def draw_landmarks(
        self,
        frame: np.ndarray,
        raw_landmarks,
        draw_tesselation: bool = False
    ) -> np.ndarray:
        """
        Draw facial landmarks on frame.
        
        Args:
            frame: Frame to draw on
            raw_landmarks: MediaPipe landmarks object
            draw_tesselation: Whether to draw face mesh
        
        Returns:
            Frame with landmarks drawn
        """
        output = frame.copy()
        
        if self.mp_drawing and self.mp_face_mesh and raw_landmarks:
            try:
                if draw_tesselation:
                    self.mp_drawing.draw_landmarks(
                        image=output,
                        landmark_list=raw_landmarks,
                        connections=self.mp_face_mesh.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=self.mp_drawing_styles.get_default_face_mesh_tesselation_style()
                    )
                
                # Draw contours
                self.mp_drawing.draw_landmarks(
                    image=output,
                    landmark_list=raw_landmarks,
                    connections=self.mp_face_mesh.FACEMESH_CONTOURS,
                    landmark_drawing_spec=None,
                    connection_drawing_spec=self.mp_drawing_styles.get_default_face_mesh_contours_style()
                )
            except Exception:
                pass
        
        return output
    
    def release(self):
        """Release resources safely."""
        if self._task_landmarker:
            try:
                self._task_landmarker.close()
            except Exception:
                pass
            self._task_landmarker = None
        if self.face_mesh:
            try:
                self.face_mesh.close()
            except Exception:
                pass
            self.face_mesh = None


class EngagementTracker:
    """
    Engagement Tracker for monitoring student attention.
    
    Combines eye metrics, head pose, and blink analysis to calculate
    an overall engagement score and categorize attention level.
    """
    
    def __init__(self, history_size: int = 90):
        """
        Initialize engagement tracker.
        
        Args:
            history_size: Number of frames to keep in history (for smoothing)
        """
        self.analyzer = FaceMeshAnalyzer(max_faces=config.detection.max_faces)
        
        # Per-face tracking data
        self._face_data: Dict[int, Dict] = {}
        self.history_size = history_size
        
        # Weights from config
        self.ear_weight = config.engagement.ear_weight
        self.head_pose_weight = config.engagement.head_pose_weight
        self.blink_weight = config.engagement.blink_weight
        
        logger.info("EngagementTracker initialized")
    
    def _get_or_create_face_data(self, face_id: int) -> Dict:
        """Get or create tracking data for a face."""
        if face_id not in self._face_data:
            self._face_data[face_id] = {
                'ear_history': deque(maxlen=self.history_size),
                'blink_times': deque(maxlen=60),  # Track last 60 blinks
                'eyes_closed_frames': 0,
                'last_ear': 0.30,
                'created_at': datetime.now(),
                'engagement_history': deque(maxlen=self.history_size),
                'head_pose_history': deque(maxlen=self.history_size)
            }
        return self._face_data[face_id]
    
    def track(self, frame: np.ndarray, detections: Optional[List] = None) -> List[Tuple[int, EngagementMetrics]]:
        """
        Track engagement for all faces in frame.
        
        Args:
            frame: BGR image
            detections: Optional list of FaceDetection objects
        
        Returns:
            List of (face_id, EngagementMetrics) tuples
        """
        results = []
        faces_data = self.analyzer.process(frame)
        
        # Match detections to detected landmark faces by spatial proximity
        matched_face_data = []
        if detections:
            used_lm_indices = set()
            for det in detections:
                det_cx, det_cy = det.center
                best_idx = None
                best_dist = float('inf')
                for i, fd in enumerate(faces_data):
                    if i in used_lm_indices:
                        continue
                    if 'center' in fd:
                        fcx, fcy = fd['center']
                    else:
                        fcx = fd['landmarks'][1][0]
                        fcy = fd['landmarks'][1][1]
                    dist = ((det_cx - fcx)**2 + (det_cy - fcy)**2) ** 0.5
                    max_dim = max(det.bbox[2], det.bbox[3]) * 1.5
                    if dist < max_dim and dist < best_dist:
                        best_dist = dist
                        best_idx = i
                
                if best_idx is not None:
                    used_lm_indices.add(best_idx)
                    matched_face_data.append(faces_data[best_idx])
                else:
                    x, y, w, h = det.bbox
                    landmarks = self.analyzer._estimate_landmarks_from_box(x, y, w, h)
                    matched_face_data.append({
                        'landmarks': landmarks,
                        'raw_landmarks': None,
                        'blendshapes': {},
                        'estimated': True
                    })
        else:
            matched_face_data = faces_data
        
        for face_id, face_data in enumerate(matched_face_data):
            landmarks = face_data['landmarks']
            
            # Get tracking data for this face
            track_data = self._get_or_create_face_data(face_id)
            
            # Calculate EAR
            left_ear, right_ear = self.analyzer.calculate_ear(landmarks)
            avg_ear = (left_ear + right_ear) / 2.0
            
            # Update EAR history
            track_data['ear_history'].append(avg_ear)
            
            # Detect blink (using EAR and blendshapes)
            blendshapes = face_data.get('blendshapes', {})
            is_blinking = self._detect_blink(track_data, avg_ear, blendshapes)
            
            # Update eyes closed counter
            if avg_ear < config.engagement.ear_threshold:
                track_data['eyes_closed_frames'] += 1
            else:
                track_data['eyes_closed_frames'] = 0
            
            # Calculate blink rate (blinks per minute)
            blink_rate = self._calculate_blink_rate(track_data)
            
            # Estimate head pose
            head_pose = self.analyzer.estimate_head_pose(landmarks)
            track_data['head_pose_history'].append(head_pose)
            
            # Create eye metrics
            eye_metrics = EyeMetrics(
                left_ear=left_ear,
                right_ear=right_ear,
                average_ear=avg_ear,
                is_blinking=is_blinking,
                eyes_closed_frames=track_data['eyes_closed_frames']
            )
            
            # Calculate engagement score
            engagement_score = self._calculate_engagement_score(
                eye_metrics, head_pose, blink_rate
            )
            
            # Smooth engagement score
            track_data['engagement_history'].append(engagement_score)
            smoothed_score = float(np.mean(list(track_data['engagement_history'])))
            
            # Determine status
            status = self._determine_status(eye_metrics, smoothed_score)
            
            # Create metrics object
            metrics = EngagementMetrics(
                head_pose=head_pose,
                eye_metrics=eye_metrics,
                blink_rate=blink_rate,
                engagement_score=smoothed_score,
                status=status
            )
            
            results.append((face_id, metrics))
        
        return results
    
    def _detect_blink(self, track_data: Dict, current_ear: float, blendshapes: Optional[Dict] = None) -> bool:
        """Detect a complete blink cycle (open -> closed -> re-opened)."""
        threshold = config.engagement.blink_threshold
        now = datetime.now()
        
        # Check if eyes are currently closed (either low EAR or high blendshape blink score)
        blend_closed = False
        if blendshapes:
            left_b = blendshapes.get('eyeBlinkLeft', 0.0)
            right_b = blendshapes.get('eyeBlinkRight', 0.0)
            if left_b > 0.55 and right_b > 0.55:
                blend_closed = True
                
        is_closed = (current_ear < threshold) or blend_closed
        
        closed_frames = track_data.get('blink_closed_frames', 0)
        is_blinking = False
        
        if is_closed:
            track_data['blink_closed_frames'] = closed_frames + 1
            is_blinking = True
        else:
            # Eyes are currently open. If they were closed for 1 to 10 frames (~30ms to 400ms), that's a completed blink!
            if 1 <= closed_frames <= 10:
                last_blink_time = track_data['blink_times'][-1] if track_data['blink_times'] else None
                if last_blink_time is None or (now - last_blink_time).total_seconds() > 0.25:
                    track_data['blink_times'].append(now)
            track_data['blink_closed_frames'] = 0
            
        track_data['last_ear'] = current_ear
        return is_blinking
    
    def _calculate_blink_rate(self, track_data: Dict) -> float:
        """Calculate blinks per minute with smooth startup ramping."""
        now = datetime.now()
        one_minute_ago = now - timedelta(minutes=1)
        
        # Count completed blinks in the last 60 seconds
        recent_blinks = [
            t for t in track_data['blink_times']
            if t > one_minute_ago
        ]
        
        created_at = track_data.get('created_at', now)
        elapsed = (now - created_at).total_seconds()
        
        # Before 30 seconds of observation, blend the actual count with standard normal rate (17 bpm)
        if elapsed < 30.0:
            weight = max(0.0, elapsed / 30.0)
            extrapolated = float(len(recent_blinks)) * (60.0 / max(5.0, elapsed))
            extrapolated = min(35.0, max(8.0, extrapolated))
            return round((1.0 - weight) * 17.0 + weight * extrapolated, 1)
        else:
            return float(len(recent_blinks))
    
    def _calculate_engagement_score(
        self,
        eye_metrics: EyeMetrics,
        head_pose: HeadPose,
        blink_rate: float
    ) -> float:
        """
        Calculate overall engagement score (0-100).
        
        Components:
        - EAR score: Higher EAR = more alert
        - Head pose score: Looking forward = more engaged
        - Blink score: Normal blink rate = engaged
        """
        # EAR score (0-100)
        ear_score = min(100, (eye_metrics.average_ear / 0.3) * 100)
        
        # Penalize if eyes closed too long
        if eye_metrics.is_sleeping:
            ear_score = 0
        
        # Head pose score
        head_score = head_pose.get_attention_score()
        
        # Blink rate score (normal is 15-20 per minute)
        min_blink, max_blink = config.engagement.normal_blink_rate
        if min_blink <= blink_rate <= max_blink:
            blink_score = 100
        elif blink_rate < min_blink:
            blink_score = max(0, 50 + (blink_rate / min_blink) * 50)
        else:
            # Too many blinks might indicate fatigue
            blink_score = max(0, 100 - (blink_rate - max_blink) * 5)
        
        # Weighted average
        engagement = (
            ear_score * self.ear_weight +
            head_score * self.head_pose_weight +
            blink_score * self.blink_weight
        )
        
        return min(100, max(0, engagement))
    
    def _determine_status(
        self,
        eye_metrics: EyeMetrics,
        engagement_score: float
    ) -> EngagementStatus:
        """Determine engagement status from metrics."""
        if eye_metrics.is_sleeping:
            return EngagementStatus.SLEEPING
        
        if engagement_score >= config.engagement.attentive_threshold:
            return EngagementStatus.ATTENTIVE
        elif engagement_score >= config.engagement.distracted_threshold:
            return EngagementStatus.DISTRACTED
        else:
            return EngagementStatus.SLEEPING
    
    def get_face_metrics(self, face_id: int) -> Optional[EngagementMetrics]:
        """Get latest metrics for a specific face."""
        if face_id in self._face_data:
            data = self._face_data[face_id]
            if data['engagement_history']:
                score = list(data['engagement_history'])[-1]
                return EngagementMetrics(engagement_score=score)
        return None
    
    def reset(self, face_id: int = None):
        """Reset tracking data."""
        if face_id is not None:
            if face_id in self._face_data:
                del self._face_data[face_id]
        else:
            self._face_data.clear()
    
    def draw_metrics(
        self,
        frame: np.ndarray,
        metrics: EngagementMetrics,
        position: Tuple[int, int]
    ) -> np.ndarray:
        """
        Draw engagement metrics on frame.
        
        Args:
            frame: Frame to draw on
            metrics: Engagement metrics
            position: (x, y) position to draw
        
        Returns:
            Frame with metrics drawn
        """
        output = frame.copy()
        x, y = position
        
        # Color based on status
        color_map = {
            EngagementStatus.ATTENTIVE: (0, 255, 0),    # Green
            EngagementStatus.DISTRACTED: (0, 165, 255), # Orange
            EngagementStatus.SLEEPING: (0, 0, 255),     # Red
            EngagementStatus.UNKNOWN: (128, 128, 128)   # Gray
        }
        color = color_map.get(metrics.status, (255, 255, 255))
        
        # Draw status
        cv2.putText(
            output, f"{metrics.status.value}",
            (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
        )
        
        # Draw score
        cv2.putText(
            output, f"Score: {metrics.engagement_score:.1f}%",
            (x, y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
        )
        
        # Draw EAR
        cv2.putText(
            output, f"EAR: {metrics.eye_metrics.average_ear:.2f}",
            (x, y + 45), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1
        )
        
        return output
    
    def release(self):
        """Release resources."""
        self.analyzer.release()


class StudentEngagementAnalyzer:
    """
    High-level analyzer for tracking individual student engagement over time.
    
    Maintains engagement history and statistics per student.
    """
    
    def __init__(self):
        """Initialize student engagement analyzer."""
        self.tracker = EngagementTracker()
        self._student_data: Dict[str, Dict] = {}
    
    def update_student(
        self,
        student_name: str,
        metrics: EngagementMetrics
    ):
        """Update engagement data for a student."""
        if student_name not in self._student_data:
            self._student_data[student_name] = {
                'history': [],
                'total_frames': 0,
                'attentive_frames': 0,
                'distracted_frames': 0,
                'sleeping_frames': 0
            }
        
        data = self._student_data[student_name]
        data['history'].append(metrics)
        data['total_frames'] += 1
        
        if metrics.status == EngagementStatus.ATTENTIVE:
            data['attentive_frames'] += 1
        elif metrics.status == EngagementStatus.DISTRACTED:
            data['distracted_frames'] += 1
        elif metrics.status == EngagementStatus.SLEEPING:
            data['sleeping_frames'] += 1
        
        # Keep only last hour of data
        max_history = 3600 * 30  # Assuming ~30 fps
        if len(data['history']) > max_history:
            data['history'] = data['history'][-max_history:]
    
    def get_student_stats(self, student_name: str) -> Dict:
        """Get engagement statistics for a student."""
        if student_name not in self._student_data:
            return {}
        
        data = self._student_data[student_name]
        total = data['total_frames']
        
        if total == 0:
            return {}
        
        recent_history = data['history'][-100:]  # Last ~3 seconds
        if recent_history:
            avg_score = np.mean([m.engagement_score for m in recent_history])
        else:
            avg_score = 0
        
        return {
            'average_engagement': avg_score,
            'attentive_percentage': (data['attentive_frames'] / total) * 100,
            'distracted_percentage': (data['distracted_frames'] / total) * 100,
            'sleeping_percentage': (data['sleeping_frames'] / total) * 100,
            'total_frames_analyzed': total
        }
    
    def get_all_student_stats(self) -> Dict[str, Dict]:
        """Get statistics for all tracked students."""
        return {name: self.get_student_stats(name) for name in self._student_data}
    
    def get_class_engagement(self) -> float:
        """Get average engagement score across all students."""
        all_stats = self.get_all_student_stats()
        if not all_stats:
            return 0.0
        
        scores = [s.get('average_engagement', 0) for s in all_stats.values()]
        return np.mean(scores) if scores else 0.0
    
    def release(self):
        """Release resources."""
        self.tracker.release()


# Convenience function
def analyze_engagement(frame: np.ndarray) -> List[EngagementMetrics]:
    """
    Quick utility to analyze engagement in a frame.
    
    Args:
        frame: BGR image
    
    Returns:
        List of EngagementMetrics for each face
    """
    tracker = EngagementTracker()
    results = tracker.track(frame)
    return [metrics for _, metrics in results]
