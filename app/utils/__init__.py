"""
Utility Module for Common Functions and Helpers.

This module provides:
- Logging configuration
- Camera management
- Image processing utilities
- Video streaming helpers
- Dataset collection tools

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional, Tuple, List, Callable
from queue import Queue
from threading import Thread, Event
import time
from logging.handlers import RotatingFileHandler

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import config


# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging(
    name: str = None,
    log_file: str = None,
    console_level: str = None,
    file_level: str = None
) -> logging.Logger:
    """
    Set up logging configuration.
    
    Args:
        name: Logger name (defaults to root logger)
        log_file: Log file path
        console_level: Console logging level
        file_level: File logging level
    
    Returns:
        Configured logger instance
    """
    # Get or create logger
    logger = logging.getLogger(name)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Set base level to DEBUG to allow handlers to filter
    logger.setLevel(logging.DEBUG)
    
    # Create formatters
    log_format = config.logging.log_format
    date_format = config.logging.date_format
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(
        getattr(logging, console_level or config.logging.console_level)
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    log_dir = config.logging.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_path = log_dir / (log_file or config.logging.log_file)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=config.logging.max_bytes,
        backupCount=config.logging.backup_count
    )
    file_handler.setLevel(
        getattr(logging, file_level or config.logging.file_level)
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


# Initialize root logger
root_logger = setup_logging()


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# ============================================================================
# Camera Management
# ============================================================================

class CameraStream:
    """
    Camera Stream Manager with buffering and threading.
    
    Provides efficient video capture with frame buffering
    for smooth real-time processing.
    """
    
    def __init__(
        self,
        source: int = None,
        width: int = None,
        height: int = None,
        fps: int = None,
        buffer_size: int = None
    ):
        """
        Initialize camera stream.
        
        Args:
            source: Camera index or video file path
            width: Frame width
            height: Frame height
            fps: Frames per second
            buffer_size: Frame buffer size
        """
        self.source = source if source is not None else config.camera.camera_index
        self.width = width or config.camera.frame_width
        self.height = height or config.camera.frame_height
        self.fps = fps or config.camera.fps
        self.buffer_size = buffer_size or config.camera.buffer_size
        
        self._cap = None
        self._frame_queue = Queue(maxsize=self.buffer_size)
        self._stop_event = Event()
        self._thread = None
        self._last_frame = None
        
        self.logger = get_logger(__name__)
    
    def start(self) -> bool:
        """
        Start the camera stream.
        
        Returns:
            True if started successfully
        """
        try:
            self._cap = cv2.VideoCapture(self.source)
            
            if not self._cap.isOpened():
                self.logger.error(f"Failed to open camera {self.source}")
                return False
            
            # Set camera properties
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
            
            # Start capture thread
            self._stop_event.clear()
            self._thread = Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            
            self.logger.info(f"Camera stream started from source {self.source}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error starting camera: {e}")
            return False
    
    def _capture_loop(self):
        """Background thread for capturing frames."""
        while not self._stop_event.is_set():
            if self._cap and self._cap.isOpened():
                ret, frame = self._cap.read()
                if ret:
                    # Update last frame
                    self._last_frame = frame
                    
                    # Add to queue (non-blocking)
                    if not self._frame_queue.full():
                        self._frame_queue.put(frame)
                else:
                    time.sleep(0.01)
            else:
                break
    
    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read a frame from the stream.
        
        Returns:
            Tuple of (success, frame)
        """
        if self._last_frame is not None:
            return True, self._last_frame.copy()
        return False, None
    
    def read_latest(self) -> Optional[np.ndarray]:
        """
        Get the most recent frame.
        
        Returns:
            Latest frame or None
        """
        return self._last_frame.copy() if self._last_frame is not None else None
    
    def stop(self):
        """Stop the camera stream."""
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=1.0)
        
        if self._cap:
            self._cap.release()
            self._cap = None
        
        self.logger.info("Camera stream stopped")
    
    def is_opened(self) -> bool:
        """Check if camera is opened."""
        return self._cap is not None and self._cap.isOpened()
    
    def get_frame_size(self) -> Tuple[int, int]:
        """Get actual frame dimensions."""
        if self._cap:
            width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return width, height
        return self.width, self.height
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


def generate_frames(camera: CameraStream) -> Generator[bytes, None, None]:
    """
    Generate JPEG frames for streaming.
    
    Args:
        camera: CameraStream instance
    
    Yields:
        JPEG encoded frame bytes
    """
    while True:
        frame = camera.read_latest()
        if frame is None:
            continue
        
        # Encode frame to JPEG
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ret:
            continue
        
        frame_bytes = buffer.tobytes()
        
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n'
        )


# ============================================================================
# Image Processing Utilities
# ============================================================================

def resize_frame(
    frame: np.ndarray,
    width: int = None,
    height: int = None,
    keep_aspect: bool = True
) -> np.ndarray:
    """
    Resize a frame.
    
    Args:
        frame: Input frame
        width: Target width
        height: Target height
        keep_aspect: Maintain aspect ratio
    
    Returns:
        Resized frame
    """
    if frame is None:
        return None
    
    h, w = frame.shape[:2]
    
    if width is None and height is None:
        return frame
    
    if keep_aspect:
        if width is not None:
            ratio = width / w
            new_size = (width, int(h * ratio))
        else:
            ratio = height / h
            new_size = (int(w * ratio), height)
    else:
        new_size = (width or w, height or h)
    
    return cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)


def adjust_brightness(
    frame: np.ndarray,
    factor: float = 1.0
) -> np.ndarray:
    """
    Adjust frame brightness.
    
    Args:
        frame: Input frame
        factor: Brightness factor (>1 = brighter, <1 = darker)
    
    Returns:
        Adjusted frame
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hsv = hsv.astype(np.float32)
    hsv[:, :, 2] *= factor
    hsv[:, :, 2] = np.clip(hsv[:, :, 2], 0, 255)
    hsv = hsv.astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def enhance_low_light(frame: np.ndarray) -> np.ndarray:
    """
    Enhance frame for low-light conditions.
    
    Args:
        frame: Input frame
    
    Returns:
        Enhanced frame
    """
    # Convert to LAB color space
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    
    # Apply CLAHE to L channel
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    
    # Convert back to BGR
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def draw_text_with_background(
    frame: np.ndarray,
    text: str,
    position: Tuple[int, int],
    font_scale: float = 0.6,
    color: Tuple[int, int, int] = (255, 255, 255),
    bg_color: Tuple[int, int, int] = (0, 0, 0),
    thickness: int = 1,
    padding: int = 5
) -> np.ndarray:
    """
    Draw text with background rectangle.
    
    Args:
        frame: Frame to draw on
        text: Text to draw
        position: (x, y) position
        font_scale: Font scale
        color: Text color
        bg_color: Background color
        thickness: Text thickness
        padding: Background padding
    
    Returns:
        Frame with text drawn
    """
    font = cv2.FONT_HERSHEY_SIMPLEX
    
    # Get text size
    (text_width, text_height), baseline = cv2.getTextSize(
        text, font, font_scale, thickness
    )
    
    x, y = position
    
    # Draw background
    cv2.rectangle(
        frame,
        (x - padding, y - text_height - padding),
        (x + text_width + padding, y + baseline + padding),
        bg_color,
        -1
    )
    
    # Draw text
    cv2.putText(frame, text, (x, y), font, font_scale, color, thickness)
    
    return frame


# ============================================================================
# Dataset Collection
# ============================================================================

class DatasetCollector:
    """
    Dataset Collector for capturing student face images.
    
    Provides guided face image collection for training the
    recognition system.
    """
    
    def __init__(
        self,
        dataset_path: Path = None,
        images_per_student: int = 10
    ):
        """
        Initialize dataset collector.
        
        Args:
            dataset_path: Path to save images
            images_per_student: Number of images to capture
        """
        self.dataset_path = Path(dataset_path or config.recognition.dataset_path)
        self.images_per_student = images_per_student
        self.logger = get_logger(__name__)
        
        self.dataset_path.mkdir(parents=True, exist_ok=True)
    
    def collect_images(
        self,
        student_name: str,
        camera: CameraStream,
        face_detector,
        on_progress: Callable[[int, int], None] = None,
        delay_between_captures: float = 0.5
    ) -> List[Path]:
        """
        Collect face images for a student.
        
        Args:
            student_name: Name of the student
            camera: CameraStream instance
            face_detector: FaceDetector instance
            on_progress: Progress callback(current, total)
            delay_between_captures: Delay in seconds between captures
        
        Returns:
            List of saved image paths
        """
        student_dir = self.dataset_path / student_name.replace(" ", "_")
        student_dir.mkdir(parents=True, exist_ok=True)
        
        saved_paths = []
        count = 0
        
        self.logger.info(f"Starting image collection for {student_name}")
        
        while count < self.images_per_student:
            frame = camera.read_latest()
            if frame is None:
                continue
            
            # Detect faces
            detections = face_detector.detect(frame, skip_frames=False)
            
            if len(detections) == 1:  # Single face in frame
                det = detections[0]
                face_img = face_detector.extract_face(frame, det)
                
                if face_img is not None and face_img.size > 0:
                    # Save image
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    img_path = student_dir / f"{student_name}_{timestamp}.jpg"
                    cv2.imwrite(str(img_path), face_img)
                    
                    saved_paths.append(img_path)
                    count += 1
                    
                    if on_progress:
                        on_progress(count, self.images_per_student)
                    
                    self.logger.debug(f"Captured image {count}/{self.images_per_student}")
                    time.sleep(delay_between_captures)
        
        self.logger.info(f"Collected {len(saved_paths)} images for {student_name}")
        return saved_paths
    
    def get_existing_students(self) -> List[str]:
        """Get list of students with existing datasets."""
        if not self.dataset_path.exists():
            return []
        
        return [
            d.name for d in self.dataset_path.iterdir()
            if d.is_dir() and any(d.glob("*.jpg"))
        ]
    
    def delete_student_dataset(self, student_name: str) -> bool:
        """Delete dataset for a student."""
        student_dir = self.dataset_path / student_name.replace(" ", "_")
        
        if student_dir.exists():
            import shutil
            shutil.rmtree(student_dir)
            self.logger.info(f"Deleted dataset for {student_name}")
            return True
        
        return False


# ============================================================================
# Miscellaneous Utilities
# ============================================================================

def get_timestamp() -> str:
    """Get current timestamp string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_system_info() -> dict:
    """Get system information for debugging."""
    import platform
    
    return {
        'python_version': platform.python_version(),
        'platform': platform.platform(),
        'opencv_version': cv2.__version__,
        'timestamp': get_timestamp()
    }


class FPSCounter:
    """FPS counter for performance monitoring."""
    
    def __init__(self, window_size: int = 30):
        """
        Initialize FPS counter.
        
        Args:
            window_size: Number of frames for averaging
        """
        self._times = []
        self._window_size = window_size
    
    def tick(self) -> float:
        """
        Record a frame and return current FPS.
        
        Returns:
            Current FPS
        """
        now = time.time()
        self._times.append(now)
        
        # Keep only recent times
        self._times = self._times[-self._window_size:]
        
        if len(self._times) < 2:
            return 0.0
        
        elapsed = self._times[-1] - self._times[0]
        if elapsed == 0:
            return 0.0
        
        return (len(self._times) - 1) / elapsed
    
    def get_fps(self) -> float:
        """Get current FPS without recording a frame."""
        if len(self._times) < 2:
            return 0.0
        
        elapsed = self._times[-1] - self._times[0]
        if elapsed == 0:
            return 0.0
        
        return (len(self._times) - 1) / elapsed
