"""
Configuration Module for Real-Time Classroom Attendance and Engagement System.

This module contains all configurable parameters for the system including
detection thresholds, database settings, engagement parameters, and Flask config.

Author: AI Engineer
Version: 1.0.0
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Tuple
from pathlib import Path


# Base directory
BASE_DIR = Path(__file__).parent.absolute()


@dataclass
class DetectionConfig:
    """Configuration for face detection module."""
    
    # MediaPipe Face Detection settings
    min_detection_confidence: float = 0.5
    model_selection: int = 1  # 0 for short-range, 1 for full-range
    
    # Processing settings
    max_faces: int = 20
    frame_skip: int = 2  # Process every nth frame for performance
    
    # Bounding box expansion factor
    bbox_expansion: float = 0.1


@dataclass
class RecognitionConfig:
    """Configuration for face recognition module."""
    
    # Recognition thresholds
    recognition_threshold: float = 0.6  # Euclidean distance threshold
    unknown_threshold: float = 0.5  # Below this, face is unknown
    
    # Encoding settings
    encoding_model: str = "large"  # 'small' or 'large'
    num_jitters: int = 1  # Higher = more accurate but slower
    
    # Paths
    encodings_path: Path = BASE_DIR / "models" / "encodings.pkl"
    dataset_path: Path = BASE_DIR / "dataset"
    
    # Duplicate prevention
    attendance_cooldown_minutes: int = 30  # Minimum time between attendance marks


@dataclass
class EngagementConfig:
    """Configuration for engagement tracking module."""
    
    # Eye Aspect Ratio (EAR) thresholds
    ear_threshold: float = 0.21  # Below this = eyes closed
    ear_consecutive_frames: int = 20  # Frames for sleep detection
    
    # Blink detection
    blink_threshold: float = 0.25
    normal_blink_rate: Tuple[int, int] = (15, 20)  # blinks per minute range
    
    # Head pose thresholds (degrees)
    yaw_threshold: float = 30.0  # Looking left/right
    pitch_threshold: float = 25.0  # Looking up/down
    roll_threshold: float = 25.0  # Head tilt
    
    # Engagement scoring weights
    ear_weight: float = 0.3
    head_pose_weight: float = 0.4
    blink_weight: float = 0.3
    
    # Engagement categories
    attentive_threshold: float = 70.0
    distracted_threshold: float = 40.0
    # Below distracted_threshold = sleeping
    
    # Liveness detection
    liveness_blink_required: bool = True
    liveness_timeout_seconds: int = 5


@dataclass
class DatabaseConfig:
    """Configuration for database module."""
    
    # SQLite settings
    database_path: Path = BASE_DIR / "attendance.db"
    
    # Table names
    attendance_table: str = "attendance"
    students_table: str = "students"
    engagement_table: str = "engagement_logs"
    
    # Backup settings
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_path: Path = BASE_DIR / "backups"


@dataclass
class FlaskConfig:
    """Configuration for Flask web application."""
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    
    # Secret key (change in production!)
    secret_key: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Session settings
    session_lifetime_minutes: int = 60
    
    # Upload settings
    max_content_length: int = 16 * 1024 * 1024  # 16MB max upload
    allowed_extensions: Tuple[str, ...] = ("png", "jpg", "jpeg")
    
    # Template settings
    templates_auto_reload: bool = True


@dataclass
class CameraConfig:
    """Configuration for camera/video input."""
    
    # Camera settings
    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    fps: int = 30
    
    # Buffer settings
    buffer_size: int = 1
    
    # Processing
    resize_for_processing: bool = True
    processing_width: int = 640
    processing_height: int = 480


@dataclass
class LoggingConfig:
    """Configuration for logging."""
    
    # Log file settings
    log_dir: Path = BASE_DIR / "logs"
    log_file: str = "system.log"
    
    # Log levels
    console_level: str = "INFO"
    file_level: str = "DEBUG"
    
    # Format
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    
    # Rotation
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5


@dataclass
class SystemConfig:
    """Master configuration class combining all configs."""
    
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    recognition: RecognitionConfig = field(default_factory=RecognitionConfig)
    engagement: EngagementConfig = field(default_factory=EngagementConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    flask: FlaskConfig = field(default_factory=FlaskConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # System-wide settings
    app_name: str = "Real-Time Attendance & Engagement System"
    version: str = "1.0.0"
    
    def __post_init__(self):
        """Create necessary directories after initialization."""
        directories = [
            self.recognition.encodings_path.parent,
            self.recognition.dataset_path,
            self.database.backup_path,
            self.logging.log_dir,
            BASE_DIR / "static",
            BASE_DIR / "templates",
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


# Global configuration instance
config = SystemConfig()


# Environment-based configuration overrides
def load_environment_config():
    """Load configuration overrides from environment variables."""
    
    if os.environ.get("PRODUCTION"):
        config.flask.debug = False
        config.flask.secret_key = os.environ.get("SECRET_KEY", config.flask.secret_key)
    
    if os.environ.get("DATABASE_PATH"):
        config.database.database_path = Path(os.environ["DATABASE_PATH"])
    
    if os.environ.get("CAMERA_INDEX"):
        config.camera.camera_index = int(os.environ["CAMERA_INDEX"])
    
    return config


# Initialize with environment overrides
load_environment_config()
