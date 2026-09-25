"""
Face Recognition Module using DeepFace library.

This module provides face recognition capabilities using deep learning
embeddings. It handles encoding generation, storage, and real-time 
matching with duplicate prevention.

Features:
- Face encoding generation from dataset (VGG-Face, Facenet, ArcFace)
- Persistent encoding storage (pickle)
- Real-time face matching
- Liveness detection support
- Duplicate attendance prevention

Author: AI Engineer
Version: 2.0.0
"""

import cv2
import numpy as np
import pickle
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
from datetime import datetime, timedelta
import logging
from collections import defaultdict

# DeepFace for face recognition
try:
    from deepface import DeepFace
    from deepface.models.FacialRecognition import FacialRecognition
    DEEPFACE_AVAILABLE = True
except ImportError:
    DEEPFACE_AVAILABLE = False

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config


# Configure module logger
logger = logging.getLogger(__name__)

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'


@dataclass
class RecognitionResult:
    """Data class representing a recognition result."""
    
    name: str
    confidence: float  # Similarity score (higher is better)
    distance: float  # Distance metric
    encoding: Optional[np.ndarray] = None
    is_known: bool = True
    
    @property
    def is_confident(self) -> bool:
        """Check if recognition meets confidence threshold."""
        return self.confidence >= (1 - config.recognition.recognition_threshold)


@dataclass
class StudentEncoding:
    """Data class for storing student face encodings."""
    
    student_id: str
    name: str
    encodings: List[np.ndarray] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    image_paths: List[str] = field(default_factory=list)
    
    def add_encoding(self, encoding: np.ndarray, image_path: str = None):
        """Add a new encoding for this student."""
        self.encodings.append(encoding)
        if image_path:
            self.image_paths.append(image_path)


class FaceEncoder:
    """
    Face Encoder class for generating face embeddings using DeepFace.
    
    This class handles the creation of face encodings from images
    using various deep learning models (VGG-Face, Facenet, ArcFace).
    
    Attributes:
        model_name: Model to use for encoding
        detector_backend: Face detector backend
    """
    
    # Model name mapping
    MODEL_MAP = {
        'large': 'VGG-Face',  # 2622D vectors, more accurate
        'small': 'Facenet',   # 128D vectors, faster
        'arcface': 'ArcFace', # 512D vectors, best accuracy
    }
    
    def __init__(
        self,
        model: Optional[str] = None,
        num_jitters: Optional[int] = None  # Kept for API compatibility
    ):
        """
        Initialize the face encoder.
        
        Args:
            model: 'small', 'large', or 'arcface'
            num_jitters: Not used with DeepFace (API compatibility)
        """
        if not DEEPFACE_AVAILABLE:
            raise ImportError("DeepFace is not installed. Run: pip install deepface tf-keras")
        
        model_key = model or config.recognition.encoding_model
        self.model_name = self.MODEL_MAP.get(model_key, 'VGG-Face')
        self.detector_backend = 'opencv'  # Fast and reliable
        self._model = None
        
        logger.info(f"FaceEncoder initialized with model={self.model_name}")
    
    def _ensure_model_loaded(self):
        """Lazy load the model on first use."""
        if self._model is None:
            # Warm up the model by running a dummy encoding
            logger.info(f"Loading {self.model_name} model (first use)...")
            try:
                # Create a dummy image to initialize
                dummy = np.zeros((224, 224, 3), dtype=np.uint8)
                dummy[50:200, 50:200] = 128  # Gray region
                DeepFace.represent(
                    dummy,
                    model_name=self.model_name,
                    detector_backend='skip',
                    enforce_detection=False
                )
                self._model = True
                logger.info(f"{self.model_name} model loaded successfully")
            except Exception as e:
                logger.warning(f"Model warm-up failed (this is normal): {e}")
                self._model = True
    
    def encode_face(
        self,
        image: np.ndarray,
        face_locations: List[Tuple] = None
    ) -> List[np.ndarray]:
        """
        Generate face encodings from an image.
        
        Args:
            image: BGR or RGB image as numpy array
            face_locations: Optional list of face locations (not used with DeepFace)
        
        Returns:
            List of face encodings
        """
        self._ensure_model_loaded()
        
        try:
            # DeepFace expects BGR (OpenCV format)
            if len(image.shape) == 3 and image.shape[2] == 3:
                bgr_image = image
            else:
                return []
            
            # Get embeddings using DeepFace
            result = DeepFace.represent(
                bgr_image,
                model_name=self.model_name,
                detector_backend=self.detector_backend,
                enforce_detection=False,
                align=True
            )
            
            # Extract embeddings
            encodings = []
            if isinstance(result, list):
                for face_data in result:
                    if 'embedding' in face_data:
                        encodings.append(np.array(face_data['embedding']))
            
            return encodings
            
        except Exception as e:
            logger.debug(f"Error encoding face: {e}")
            return []
    
    def encode_from_file(self, image_path: str) -> List[np.ndarray]:
        """
        Generate face encodings from an image file.
        
        Args:
            image_path: Path to image file
        
        Returns:
            List of face encodings
        """
        self._ensure_model_loaded()
        
        try:
            # Use DeepFace's built-in file loading
            result = DeepFace.represent(
                image_path,
                model_name=self.model_name,
                detector_backend=self.detector_backend,
                enforce_detection=False,
                align=True
            )
            
            encodings = []
            if isinstance(result, list):
                for face_data in result:
                    if 'embedding' in face_data:
                        encodings.append(np.array(face_data['embedding']))
            
            return encodings
            
        except Exception as e:
            logger.debug(f"Error loading image {image_path}: {e}")
            return []


class DatasetEncoder:
    """
    Dataset Encoder for batch processing student images.
    
    This class handles encoding an entire dataset of student images
    and storing the results for later recognition.
    """
    
    def __init__(
        self,
        dataset_path: Optional[Path] = None,
        encodings_path: Optional[Path] = None
    ):
        """
        Initialize the dataset encoder.
        
        Args:
            dataset_path: Path to dataset folder
            encodings_path: Path to save/load encodings
        """
        self.dataset_path = Path(dataset_path or config.recognition.dataset_path)
        self.encodings_path = Path(encodings_path or config.recognition.encodings_path)
        self.encoder = FaceEncoder()
        self.student_encodings: Dict[str, StudentEncoding] = {}
        
        logger.info(f"DatasetEncoder initialized with dataset={self.dataset_path}")
    
    def encode_dataset(self, progress_callback=None) -> Dict[str, StudentEncoding]:
        """
        Encode all faces in the dataset.
        
        Expected dataset structure:
        dataset/
            student_1/
                img1.jpg
                img2.jpg
            student_2/
                img1.jpg
        
        Args:
            progress_callback: Optional callback(current, total, name) for progress
        
        Returns:
            Dictionary of student encodings
        """
        if not self.dataset_path.exists():
            logger.error(f"Dataset path does not exist: {self.dataset_path}")
            return {}
        
        self.student_encodings = {}
        student_dirs = [d for d in self.dataset_path.iterdir() if d.is_dir()]
        total = len(student_dirs)
        
        logger.info(f"Starting to encode {total} students")
        
        for idx, student_dir in enumerate(student_dirs):
            student_name = student_dir.name
            student_id = student_name.lower().replace(" ", "_")
            
            if progress_callback:
                progress_callback(idx + 1, total, student_name)
            
            student_enc = StudentEncoding(
                student_id=student_id,
                name=student_name
            )
            
            # Get all image files
            image_extensions = ('*.jpg', '*.jpeg', '*.png', '*.bmp')
            image_files = []
            for ext in image_extensions:
                image_files.extend(student_dir.glob(ext))
            
            for img_path in image_files:
                encodings = self.encoder.encode_from_file(str(img_path))
                
                for encoding in encodings:
                    student_enc.add_encoding(encoding, str(img_path))
            
            if student_enc.encodings:
                self.student_encodings[student_id] = student_enc
                logger.info(f"Encoded {len(student_enc.encodings)} faces for {student_name}")
            else:
                logger.warning(f"No faces found for {student_name}")
        
        logger.info(f"Dataset encoding complete: {len(self.student_encodings)} students")
        return self.student_encodings
    
    def save_encodings(self) -> bool:
        """
        Save encodings to file.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create directory if needed
            self.encodings_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Prepare data for serialization
            save_data = {
                'encodings': {},
                'metadata': {
                    'created_at': datetime.now().isoformat(),
                    'total_students': len(self.student_encodings),
                    'model': self.encoder.model_name
                }
            }
            
            for student_id, student_enc in self.student_encodings.items():
                save_data['encodings'][student_id] = {
                    'student_id': student_enc.student_id,
                    'name': student_enc.name,
                    'encodings': [enc.tolist() for enc in student_enc.encodings],
                    'image_paths': student_enc.image_paths,
                    'created_at': student_enc.created_at.isoformat()
                }
            
            with open(self.encodings_path, 'wb') as f:
                pickle.dump(save_data, f)
            
            logger.info(f"Encodings saved to {self.encodings_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving encodings: {e}")
            return False
    
    def load_encodings(self) -> bool:
        """
        Load encodings from file.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.encodings_path.exists():
                logger.warning(f"Encodings file not found: {self.encodings_path}")
                return False
            
            with open(self.encodings_path, 'rb') as f:
                save_data = pickle.load(f)
            
            self.student_encodings = {}
            
            for student_id, data in save_data.get('encodings', {}).items():
                student_enc = StudentEncoding(
                    student_id=data['student_id'],
                    name=data['name'],
                    encodings=[np.array(enc) for enc in data['encodings']],
                    image_paths=data.get('image_paths', []),
                    created_at=datetime.fromisoformat(data['created_at'])
                )
                self.student_encodings[student_id] = student_enc
            
            logger.info(f"Loaded encodings for {len(self.student_encodings)} students")
            return True
            
        except Exception as e:
            logger.error(f"Error loading encodings: {e}")
            return False


class FaceRecognizer:
    """
    Face Recognition class for real-time face matching.
    
    This class provides real-time face recognition capabilities with
    duplicate attendance prevention and confidence scoring.
    
    Attributes:
        threshold: Distance threshold for recognition
        student_encodings: Dictionary of known student encodings
    """
    
    def __init__(
        self,
        encodings_path: Optional[Path] = None,
        threshold: Optional[float] = None
    ):
        """
        Initialize the face recognizer.
        
        Args:
            encodings_path: Path to encodings file
            threshold: Distance threshold for recognition
        """
        self.encodings_path = Path(encodings_path or config.recognition.encodings_path)
        self.threshold = threshold or config.recognition.recognition_threshold
        
        self.encoder = FaceEncoder()
        self.dataset_encoder = DatasetEncoder(encodings_path=self.encodings_path)
        
        # Known encodings
        self.known_names: List[str] = []
        self.known_encodings: List[np.ndarray] = []
        self.name_to_student: Dict[str, StudentEncoding] = {}
        
        # Attendance tracking for duplicate prevention
        self._attendance_log: Dict[str, datetime] = defaultdict(lambda: datetime.min)
        
        # Load encodings if available
        self._load_known_faces()
        
        logger.info(f"FaceRecognizer initialized with {len(self.known_names)} known faces")
    
    def _load_known_faces(self):
        """Load known face encodings from file."""
        if self.dataset_encoder.load_encodings():
            self.known_names = []
            self.known_encodings = []
            self.name_to_student = {}
            
            for student_id, student_enc in self.dataset_encoder.student_encodings.items():
                for encoding in student_enc.encodings:
                    self.known_names.append(student_enc.name)
                    self.known_encodings.append(encoding)
                self.name_to_student[student_enc.name] = student_enc
    
    def reload_encodings(self):
        """Reload encodings from file."""
        self._load_known_faces()
        logger.info(f"Reloaded {len(self.known_names)} known faces")
    
    def recognize(
        self,
        face_image: np.ndarray,
        face_location: Tuple = None
    ) -> RecognitionResult:
        """
        Recognize a face from an image.
        
        Args:
            face_image: Face image as numpy array
            face_location: Optional face location tuple
        
        Returns:
            RecognitionResult object
        """
        if not self.known_encodings:
            logger.warning("No known encodings loaded")
            return RecognitionResult(
                name="Unknown",
                confidence=0.0,
                distance=1.0,
                is_known=False
            )
        
        try:
            # Get face encoding
            encodings = self.encoder.encode_face(face_image)
            
            if not encodings:
                return RecognitionResult(
                    name="Unknown",
                    confidence=0.0,
                    distance=1.0,
                    is_known=False
                )
            
            face_encoding = encodings[0]
            
            # Compare using cosine similarity
            similarities = self._compute_similarities(face_encoding)
            
            if len(similarities) == 0:
                return RecognitionResult(
                    name="Unknown",
                    confidence=0.0,
                    distance=1.0,
                    is_known=False
                )
            
            # Find best match (highest similarity)
            best_idx = np.argmax(similarities)
            best_similarity = similarities[best_idx]
            best_name = self.known_names[best_idx]
            best_distance = 1.0 - best_similarity
            
            # Check if match is confident enough
            if best_similarity >= (1.0 - self.threshold):
                return RecognitionResult(
                    name=best_name,
                    confidence=best_similarity,
                    distance=best_distance,
                    encoding=face_encoding,
                    is_known=True
                )
            else:
                return RecognitionResult(
                    name="Unknown",
                    confidence=best_similarity,
                    distance=best_distance,
                    encoding=face_encoding,
                    is_known=False
                )
                
        except Exception as e:
            logger.error(f"Error during recognition: {e}")
            return RecognitionResult(
                name="Unknown",
                confidence=0.0,
                distance=1.0,
                is_known=False
            )
    
    def _compute_similarities(self, encoding: np.ndarray) -> np.ndarray:
        """
        Compute cosine similarities between encoding and all known encodings.
        
        Args:
            encoding: Face encoding to compare
        
        Returns:
            Array of similarity scores (0-1, higher is more similar)
        """
        if not self.known_encodings:
            return np.array([])
        
        # Normalize the query encoding
        norm_encoding = encoding / (np.linalg.norm(encoding) + 1e-10)
        
        similarities = []
        for known_enc in self.known_encodings:
            # Normalize known encoding
            norm_known = known_enc / (np.linalg.norm(known_enc) + 1e-10)
            # Cosine similarity
            sim = np.dot(norm_encoding, norm_known)
            similarities.append(sim)
        
        return np.array(similarities)
    
    def recognize_multiple(
        self,
        frame: np.ndarray,
        face_locations: List[Tuple] = None
    ) -> List[Tuple[Tuple, RecognitionResult]]:
        """
        Recognize multiple faces in a frame.
        
        Args:
            frame: Full frame image
            face_locations: List of face locations (x, y, w, h) from MediaPipe
        
        Returns:
            List of (location, RecognitionResult) tuples
        """
        try:
            if face_locations is None or len(face_locations) == 0:
                return []
            
            results = []
            for location in face_locations:
                x, y, w, h = location
                # Extract face region with padding
                pad = int(min(w, h) * 0.2)
                y1 = max(0, y - pad)
                y2 = min(frame.shape[0], y + h + pad)
                x1 = max(0, x - pad)
                x2 = min(frame.shape[1], x + w + pad)
                
                face_img = frame[y1:y2, x1:x2]
                
                if face_img.size == 0:
                    continue
                
                # Recognize this face
                result = self.recognize(face_img)
                results.append((location, result))
            
            return results
            
        except Exception as e:
            logger.error(f"Error during multi-recognition: {e}")
            return []
    
    def can_mark_attendance(self, name: str) -> bool:
        """
        Check if attendance can be marked for a student.
        
        Args:
            name: Student name
        
        Returns:
            True if attendance can be marked (not duplicate)
        """
        last_marked = self._attendance_log.get(name, datetime.min)
        cooldown = timedelta(minutes=config.recognition.attendance_cooldown_minutes)
        
        return datetime.now() - last_marked > cooldown
    
    def mark_attendance_logged(self, name: str):
        """Record that attendance was marked for duplicate prevention."""
        self._attendance_log[name] = datetime.now()
    
    def clear_attendance_log(self):
        """Reset the attendance cooldown log (e.g. when changing sessions)."""
        self._attendance_log.clear()
        logger.info("Cleared recognition attendance cooldown log for session switch")
    
    def get_student_info(self, name: str) -> Optional[StudentEncoding]:
        """Get student information by name."""
        return self.name_to_student.get(name)
    
    def add_new_student(
        self,
        name: str,
        images: List[np.ndarray]
    ) -> bool:
        """
        Add a new student to the recognition system.
        
        Args:
            name: Student name
            images: List of face images
        
        Returns:
            True if successful
        """
        try:
            student_id = name.lower().replace(" ", "_")
            student_enc = StudentEncoding(
                student_id=student_id,
                name=name
            )
            
            for img in images:
                encodings = self.encoder.encode_face(img)
                for encoding in encodings:
                    student_enc.add_encoding(encoding)
                    self.known_names.append(name)
                    self.known_encodings.append(encoding)
            
            if student_enc.encodings:
                self.dataset_encoder.student_encodings[student_id] = student_enc
                self.name_to_student[name] = student_enc
                self.dataset_encoder.save_encodings()
                logger.info(f"Added new student: {name}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error adding student: {e}")
            return False


class TemporalVotingRecognizer:
    """
    Temporal Voting Recognizer for live video streams.

    Instead of trusting a single frame's recognition result, recent
    observations are aggregated per face track and an identity is only
    accepted once it accumulates a majority of votes within the
    observation window.

    Example:
        Frame 1 -> Alice 0.81
        Frame 2 -> Alice 0.85
        Frame 3 -> Unknown
        Frame 4 -> Alice 0.83
        Frame 5 -> Alice 0.88
        -> 4/5 votes for Alice => ACCEPT

    This reduces one-frame recognition errors (blur, pose, partial
    occlusion) at the cost of a small acceptance delay.
    """

    def __init__(self, window_frames: Optional[int] = None,
                 min_votes: Optional[int] = None):
        self.window = window_frames or config.temporal.window_frames
        self.min_votes = min_votes or config.temporal.min_votes
        self._votes: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        logger.info(
            f"TemporalVotingRecognizer: window={self.window}, min_votes={self.min_votes}"
        )

    def observe(self, track_key: str, name: str, similarity: float) -> Optional[str]:
        """
        Record one observation for a face track and return the accepted
        identity once the vote threshold is met.

        Args:
            track_key: stable identifier for the face track (e.g. bbox centroid bucket)
            name: recognized name ('Unknown' if not identified)
            similarity: recognition similarity score

        Returns:
            Accepted identity name, or None while votes are insufficient.
        """
        votes = self._votes[track_key][name]
        votes.append(similarity)

        # Keep only the most recent `window` observations per candidate name
        all_names = self._votes[track_key]
        for cand in all_names:
            all_names[cand] = all_names[cand][-self.window:]

        winner, count, avg_sim = self.get_consensus(track_key)
        if winner and count >= self.min_votes:
            return winner
        return None

    def get_consensus(self, track_key: str) -> Tuple[str, int, float]:
        """
        Get the current leading identity for a track.

        Returns:
            (name, vote_count, average_similarity) or ("", 0, 0.0)
        """
        track_votes = self._votes.get(track_key, {})
        best_name, best_count, best_sim = "", 0, 0.0
        for name, sims in track_votes.items():
            # 'Unknown' observations carry no identity information
            if name == "Unknown":
                continue
            if len(sims) > best_count:
                best_name, best_count = name, len(sims)
                best_sim = float(np.mean(sims)) if sims else 0.0
        return best_name, best_count, best_sim

    def reset(self, track_key: Optional[str] = None):
        """Clear vote history for one track or all tracks."""
        if track_key is None:
            self._votes.clear()
        else:
            self._votes.pop(track_key, None)


class LivenessDetector:
    """
    Liveness Detection to prevent spoofing with static images.
    
    Uses blink detection to verify the face is from a live person.
    """
    
    def __init__(self, timeout: Optional[int] = None):
        """
        Initialize liveness detector.
        
        Args:
            timeout: Seconds to wait for blink
        """
        self.timeout = timeout or config.engagement.liveness_timeout_seconds
        self.blink_detected = False
        self._last_ear = 1.0
        self._blink_counter = 0
    
    def update(self, ear: float) -> bool:
        """
        Update liveness detection with new EAR value.
        
        Args:
            ear: Eye Aspect Ratio value
        
        Returns:
            True if blink detected
        """
        threshold = config.engagement.blink_threshold
        
        # Detect blink (EAR drops then rises)
        if self._last_ear > threshold and ear < threshold:
            self._blink_counter += 1
            self.blink_detected = True
        
        self._last_ear = ear
        return self.blink_detected
    
    def reset(self):
        """Reset liveness detection state."""
        self.blink_detected = False
        self._last_ear = 1.0
        self._blink_counter = 0
    
    @property
    def is_live(self) -> bool:
        """Check if face is determined to be live."""
        return self.blink_detected


# Convenience functions
def encode_dataset(dataset_path: str = None, output_path: str = None) -> bool:
    """
    Encode all faces in a dataset directory.
    
    Args:
        dataset_path: Path to dataset folder
        output_path: Path to save encodings
    
    Returns:
        True if successful
    """
    encoder = DatasetEncoder(
        dataset_path=Path(dataset_path) if dataset_path else None,
        encodings_path=Path(output_path) if output_path else None
    )
    encoder.encode_dataset()
    return encoder.save_encodings()


def recognize_face(image: np.ndarray) -> RecognitionResult:
    """
    Quick utility to recognize a face.
    
    Args:
        image: Face image
    
    Returns:
        RecognitionResult
    """
    recognizer = FaceRecognizer()
    return recognizer.recognize(image)
