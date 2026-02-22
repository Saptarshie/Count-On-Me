"""
Face Detection Module using MediaPipe or OpenCV.

This module provides real-time multi-face detection capabilities using
Google's MediaPipe Face Detection model or OpenCV Haar Cascades as fallback.
It's optimized for classroom environments with multiple students.

Features:
- Multi-face detection (up to 20 faces)
- Adjustable confidence thresholds
- Bounding box extraction with expansion
- Performance optimization for real-time processing

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
import logging

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config

# Try to import MediaPipe (may not have solutions in newer versions)
MEDIAPIPE_AVAILABLE = False
mp = None
try:
    import mediapipe as mp
    if hasattr(mp, 'solutions') and hasattr(mp.solutions, 'face_detection'):
        MEDIAPIPE_AVAILABLE = True
except ImportError:
    pass

# Configure module logger
logger = logging.getLogger(__name__)


@dataclass
class FaceDetection:
    """Data class representing a detected face."""
    
    bbox: Tuple[int, int, int, int]  # (x, y, width, height)
    confidence: float
    landmarks: Optional[dict] = None
    face_id: Optional[int] = None
    
    @property
    def x(self) -> int:
        return self.bbox[0]
    
    @property
    def y(self) -> int:
        return self.bbox[1]
    
    @property
    def width(self) -> int:
        return self.bbox[2]
    
    @property
    def height(self) -> int:
        return self.bbox[3]
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center point of the bounding box."""
        return (self.x + self.width // 2, self.y + self.height // 2)
    
    @property
    def area(self) -> int:
        """Calculate area of bounding box."""
        return self.width * self.height
    
    def get_expanded_bbox(self, expansion: float = 0.1) -> Tuple[int, int, int, int]:
        """Get expanded bounding box for better face cropping."""
        exp_w = int(self.width * expansion)
        exp_h = int(self.height * expansion)
        return (
            max(0, self.x - exp_w),
            max(0, self.y - exp_h),
            self.width + 2 * exp_w,
            self.height + 2 * exp_h
        )


class FaceDetector:
    """
    Face Detection class using MediaPipe or OpenCV fallback.
    
    This class provides methods for detecting multiple faces in images
    and video frames with configurable parameters.
    
    Attributes:
        min_detection_confidence: Minimum confidence for detection
        model_selection: 0 for short-range, 1 for full-range detection
        max_faces: Maximum number of faces to detect
    
    Example:
        detector = FaceDetector()
        faces = detector.detect(frame)
        for face in faces:
            print(f"Face at {face.bbox} with confidence {face.confidence}")
    """
    
    def __init__(
        self,
        min_detection_confidence: Optional[float] = None,
        model_selection: Optional[int] = None,
        max_faces: Optional[int] = None
    ):
        """
        Initialize the face detector.
        
        Args:
            min_detection_confidence: Minimum confidence threshold (0.0-1.0)
            model_selection: 0 for short-range (2m), 1 for full-range (5m)
            max_faces: Maximum faces to detect per frame
        """
        self.min_detection_confidence = (
            min_detection_confidence or config.detection.min_detection_confidence
        )
        self.model_selection = model_selection or config.detection.model_selection
        self.max_faces = max_faces or config.detection.max_faces
        
        # Try MediaPipe first, fall back to OpenCV
        self.use_mediapipe = False
        self._detector = None
        self.mp_face_detection = None
        self.mp_drawing = None
        self._face_cascade = None
        
        if MEDIAPIPE_AVAILABLE:
            try:
                self.mp_face_detection = mp.solutions.face_detection
                self.mp_drawing = mp.solutions.drawing_utils
                self._detector = self.mp_face_detection.FaceDetection(
                    min_detection_confidence=self.min_detection_confidence,
                    model_selection=self.model_selection
                )
                self.use_mediapipe = True
                logger.info("Using MediaPipe for face detection")
            except Exception as e:
                logger.warning(f"MediaPipe init failed: {e}")
        
        if not self.use_mediapipe:
            # Fall back to OpenCV Haar Cascade
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self._face_cascade = cv2.CascadeClassifier(cascade_path)
            logger.info("Using OpenCV Haar Cascade for face detection")
        
        # Frame counter for processing optimization
        self._frame_count = 0
        self._cached_detections: List[FaceDetection] = []
        
        logger.info(
            f"FaceDetector initialized with confidence={self.min_detection_confidence}, "
            f"model_selection={self.model_selection}, max_faces={self.max_faces}"
        )
    
    def detect(
        self,
        frame: np.ndarray,
        skip_frames: bool = True
    ) -> List[FaceDetection]:
        """
        Detect faces in a frame.
        
        Args:
            frame: BGR image as numpy array
            skip_frames: Whether to use frame skipping for performance
        
        Returns:
            List of FaceDetection objects
        """
        if frame is None or frame.size == 0:
            logger.warning("Empty frame provided to detect()")
            return []
        
        # Frame skipping for performance
        self._frame_count += 1
        if skip_frames and self._frame_count % config.detection.frame_skip != 0:
            return self._cached_detections
        
        try:
            height, width = frame.shape[:2]
            detections = []
            
            if self.use_mediapipe and self._detector is not None:
                # Use MediaPipe
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._detector.process(rgb_frame)
                
                if results.detections:
                    for idx, detection in enumerate(results.detections[:self.max_faces]):
                        bbox_c = detection.location_data.relative_bounding_box
                        
                        x = int(bbox_c.xmin * width)
                        y = int(bbox_c.ymin * height)
                        w = int(bbox_c.width * width)
                        h = int(bbox_c.height * height)
                        
                        x = max(0, x)
                        y = max(0, y)
                        w = min(w, width - x)
                        h = min(h, height - y)
                        
                        confidence = detection.score[0]
                        landmarks = self._extract_landmarks(detection, width, height)
                        
                        face_det = FaceDetection(
                            bbox=(x, y, w, h),
                            confidence=confidence,
                            landmarks=landmarks,
                            face_id=idx
                        )
                        detections.append(face_det)
            else:
                # Use OpenCV Haar Cascade fallback
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = self._face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30)
                )
                
                for idx, (x, y, w, h) in enumerate(faces[:self.max_faces]):
                    # Haar Cascade doesn't give confidence, use threshold
                    confidence = 0.9 if w > 50 and h > 50 else 0.7
                    
                    # Estimate basic landmarks (eye positions)
                    landmarks = {
                        'left_eye': (x + w // 4, y + h // 3),
                        'right_eye': (x + 3 * w // 4, y + h // 3),
                        'nose_tip': (x + w // 2, y + h // 2),
                        'mouth_center': (x + w // 2, y + 2 * h // 3)
                    }
                    
                    face_det = FaceDetection(
                        bbox=(x, y, w, h),
                        confidence=confidence,
                        landmarks=landmarks,
                        face_id=idx
                    )
                    detections.append(face_det)
            
            # Cache detections for frame skipping
            self._cached_detections = detections
            
            logger.debug(f"Detected {len(detections)} faces in frame")
            return detections
            
        except Exception as e:
            logger.error(f"Error during face detection: {e}")
            return self._cached_detections
    
    def _extract_landmarks(
        self,
        detection,
        width: int,
        height: int
    ) -> dict:
        """
        Extract facial landmarks from detection.
        
        Args:
            detection: MediaPipe detection object
            width: Frame width
            height: Frame height
        
        Returns:
            Dictionary of landmark points
        """
        landmarks = {}
        try:
            keypoints = detection.location_data.relative_keypoints
            landmark_names = [
                'right_eye', 'left_eye', 'nose_tip',
                'mouth_center', 'right_ear_tragion', 'left_ear_tragion'
            ]
            
            for i, name in enumerate(landmark_names):
                if i < len(keypoints):
                    landmarks[name] = (
                        int(keypoints[i].x * width),
                        int(keypoints[i].y * height)
                    )
        except Exception as e:
            logger.debug(f"Could not extract landmarks: {e}")
        
        return landmarks
    
    def extract_face(
        self,
        frame: np.ndarray,
        detection: FaceDetection,
        expand: bool = True
    ) -> Optional[np.ndarray]:
        """
        Extract face region from frame.
        
        Args:
            frame: Source frame
            detection: FaceDetection object
            expand: Whether to expand bounding box
        
        Returns:
            Cropped face image or None if extraction fails
        """
        try:
            if expand:
                x, y, w, h = detection.get_expanded_bbox(config.detection.bbox_expansion)
            else:
                x, y, w, h = detection.bbox
            
            # Ensure bounds
            height, width = frame.shape[:2]
            x = max(0, x)
            y = max(0, y)
            w = min(w, width - x)
            h = min(h, height - y)
            
            if w <= 0 or h <= 0:
                return None
            
            face_img = frame[y:y+h, x:x+w].copy()
            return face_img
            
        except Exception as e:
            logger.error(f"Error extracting face: {e}")
            return None
    
    def draw_detections(
        self,
        frame: np.ndarray,
        detections: List[FaceDetection],
        draw_landmarks: bool = False,
        color: Tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2
    ) -> np.ndarray:
        """
        Draw detection boxes on frame.
        
        Args:
            frame: Frame to draw on
            detections: List of detections
            draw_landmarks: Whether to draw landmark points
            color: BGR color tuple
            thickness: Line thickness
        
        Returns:
            Frame with drawn detections
        """
        output = frame.copy()
        
        for det in detections:
            x, y, w, h = det.bbox
            
            # Draw bounding box
            cv2.rectangle(output, (x, y), (x + w, y + h), color, thickness)
            
            # Draw confidence
            conf_text = f"{det.confidence:.2f}"
            cv2.putText(
                output, conf_text, (x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
            )
            
            # Draw landmarks if requested
            if draw_landmarks and det.landmarks:
                for name, point in det.landmarks.items():
                    cv2.circle(output, point, 3, (255, 0, 0), -1)
        
        return output
    
    def release(self):
        """Release detector resources."""
        if self._detector:
            self._detector.close()
            logger.info("FaceDetector resources released")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False


class MultiScaleDetector(FaceDetector):
    """
    Multi-scale face detector for improved detection at various distances.
    
    This class extends FaceDetector to provide better detection of faces
    at different scales by processing the image at multiple resolutions.
    """
    
    def __init__(self, scales: List[float] = None, **kwargs):
        """
        Initialize multi-scale detector.
        
        Args:
            scales: List of scale factors to use
            **kwargs: Arguments passed to parent class
        """
        super().__init__(**kwargs)
        self.scales = scales or [1.0, 0.75, 0.5]
    
    def detect(
        self,
        frame: np.ndarray,
        skip_frames: bool = True
    ) -> List[FaceDetection]:
        """
        Detect faces at multiple scales.
        
        Args:
            frame: Input frame
            skip_frames: Whether to use frame skipping
        
        Returns:
            Merged list of unique detections
        """
        all_detections = []
        original_height, original_width = frame.shape[:2]
        
        for scale in self.scales:
            if scale != 1.0:
                scaled_frame = cv2.resize(
                    frame,
                    (int(original_width * scale), int(original_height * scale))
                )
            else:
                scaled_frame = frame
            
            detections = super().detect(scaled_frame, skip_frames=False)
            
            # Scale detections back to original size
            if scale != 1.0:
                for det in detections:
                    scaled_bbox = (
                        int(det.bbox[0] / scale),
                        int(det.bbox[1] / scale),
                        int(det.bbox[2] / scale),
                        int(det.bbox[3] / scale)
                    )
                    det.bbox = scaled_bbox
            
            all_detections.extend(detections)
        
        # Remove duplicate detections using NMS
        unique_detections = self._non_max_suppression(all_detections)
        
        self._cached_detections = unique_detections
        return unique_detections
    
    def _non_max_suppression(
        self,
        detections: List[FaceDetection],
        overlap_threshold: float = 0.5
    ) -> List[FaceDetection]:
        """
        Apply non-maximum suppression to remove duplicate detections.
        
        Args:
            detections: List of all detections
            overlap_threshold: IoU threshold for suppression
        
        Returns:
            Filtered list of detections
        """
        if not detections:
            return []
        
        # Sort by confidence
        detections = sorted(detections, key=lambda x: x.confidence, reverse=True)
        
        keep = []
        while detections:
            best = detections.pop(0)
            keep.append(best)
            
            detections = [
                det for det in detections
                if self._compute_iou(best.bbox, det.bbox) < overlap_threshold
            ]
        
        return keep
    
    @staticmethod
    def _compute_iou(box1: Tuple, box2: Tuple) -> float:
        """Compute Intersection over Union between two boxes."""
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2
        
        xi1 = max(x1, x2)
        yi1 = max(y1, y2)
        xi2 = min(x1 + w1, x2 + w2)
        yi2 = min(y1 + h1, y2 + h2)
        
        inter_width = max(0, xi2 - xi1)
        inter_height = max(0, yi2 - yi1)
        inter_area = inter_width * inter_height
        
        box1_area = w1 * h1
        box2_area = w2 * h2
        union_area = box1_area + box2_area - inter_area
        
        if union_area == 0:
            return 0.0
        
        return inter_area / union_area


# Convenience function for quick detection
def detect_faces(frame: np.ndarray) -> List[FaceDetection]:
    """
    Quick utility function to detect faces in a frame.
    
    Args:
        frame: BGR image as numpy array
    
    Returns:
        List of FaceDetection objects
    """
    with FaceDetector() as detector:
        return detector.detect(frame, skip_frames=False)
