"""
🎓 Automatic Dataset Capture Tool

Captures face images with guided poses for optimal recognition accuracy.
Follows best practices: multiple angles, expressions, lighting variations.

Usage:
    python collect_dataset.py --name "John Doe" --count 20

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
import os
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List

# Try to import MediaPipe (optional, will fall back to OpenCV)
MEDIAPIPE_AVAILABLE = False
try:
    import mediapipe as mp
    if hasattr(mp, 'solutions'):
        mp_face_detection = mp.solutions.face_detection
        mp_face_mesh = mp.solutions.face_mesh
        MEDIAPIPE_AVAILABLE = True
except (ImportError, AttributeError):
    pass


class DatasetCollector:
    """
    Intelligent Dataset Collector with guided pose capture.
    
    Captures face images following best practices:
    - Multiple head angles (left, right, up, down)
    - Various expressions (neutral, smile, serious)
    - Natural blinking
    - Different lighting awareness
    """
    
    # Capture instructions with emoji indicators
    CAPTURE_SEQUENCE = [
        {"instruction": "😐 Look STRAIGHT at camera", "pose": "center", "count": 3},
        {"instruction": "👈 Turn head slightly LEFT", "pose": "left", "count": 2},
        {"instruction": "👉 Turn head slightly RIGHT", "pose": "right", "count": 2},
        {"instruction": "👆 Look slightly UP", "pose": "up", "count": 2},
        {"instruction": "👇 Look slightly DOWN", "pose": "down", "count": 2},
        {"instruction": "😊 SMILE naturally", "pose": "smile", "count": 2},
        {"instruction": "😐 Neutral expression", "pose": "neutral", "count": 2},
        {"instruction": "😮 Open mouth slightly", "pose": "open_mouth", "count": 1},
        {"instruction": "😑 Close eyes briefly", "pose": "eyes_closed", "count": 1},
        {"instruction": "🔄 Move head in small circle", "pose": "motion", "count": 3},
    ]
    
    def __init__(
        self,
        dataset_path: str = "dataset",
        camera_id: int = 0,
        resolution: Tuple[int, int] = (640, 480),
        min_face_size: float = 0.15,
        quality_threshold: float = 0.7
    ):
        """
        Initialize the dataset collector.
        
        Args:
            dataset_path: Base path for dataset storage
            camera_id: Camera device ID
            resolution: Camera resolution (width, height)
            min_face_size: Minimum face size as fraction of frame
            quality_threshold: Minimum quality score for capture
        """
        self.dataset_path = Path(dataset_path)
        self.camera_id = camera_id
        self.resolution = resolution
        self.min_face_size = min_face_size
        self.quality_threshold = quality_threshold
        
        # Initialize face detection (MediaPipe or OpenCV fallback)
        self.face_detection = None
        self.face_mesh = None
        self.use_mediapipe = False
        self.face_cascade = None
        
        if MEDIAPIPE_AVAILABLE:
            try:
                self.face_detection = mp_face_detection.FaceDetection(
                    model_selection=1,
                    min_detection_confidence=0.7
                )
                self.face_mesh = mp_face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=1,
                    refine_landmarks=True,
                    min_detection_confidence=0.7,
                    min_tracking_confidence=0.7
                )
                self.use_mediapipe = True
                print("✅ Using MediaPipe for face detection")
            except Exception as e:
                print(f"⚠️ MediaPipe init failed: {e}, using OpenCV")
        
        if not self.use_mediapipe:
            # Fallback to OpenCV Haar Cascade
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            print("✅ Using OpenCV Haar Cascade for face detection")
        
        # State
        self.cap = None
        self.current_instruction_idx = 0
        self.captures_in_pose = 0
        self.total_captures = 0
        self.student_name = ""
        self.student_folder = None
        
        # Quality metrics
        self.last_quality_score = 0.0
        self.last_brightness = 0.0
        self.face_centered = False
        
    def start_camera(self) -> bool:
        """Initialize camera capture."""
        self.cap = cv2.VideoCapture(self.camera_id)
        if not self.cap.isOpened():
            print("❌ Error: Could not open camera")
            return False
        
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
        # Warm up camera
        for _ in range(10):
            self.cap.read()
        
        return True
    
    def stop_camera(self):
        """Release camera resources."""
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
    
    def create_student_folder(self, name: str) -> Path:
        """Create folder for student images."""
        # Sanitize name for folder
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        safe_name = safe_name.strip().replace(" ", "_")
        
        folder = self.dataset_path / safe_name
        folder.mkdir(parents=True, exist_ok=True)
        
        self.student_name = name
        self.student_folder = folder
        
        # Check existing images
        existing = list(folder.glob("*.jpg")) + list(folder.glob("*.png"))
        if existing:
            print(f"📁 Found {len(existing)} existing images for {name}")
        
        return folder
    
    def analyze_frame(self, frame: np.ndarray) -> dict:
        """
        Analyze frame for face quality metrics.
        
        Returns:
            Dictionary with quality metrics
        """
        h, w = frame.shape[:2]
        
        result = {
            "face_detected": False,
            "face_bbox": None,
            "face_size_ratio": 0.0,
            "centered": False,
            "brightness": 0.0,
            "blur_score": 0.0,
            "quality_score": 0.0,
            "landmarks": None,
            "head_pose": {"yaw": 0, "pitch": 0}
        }
        
        # Detect face using appropriate backend
        x, y, fw, fh = 0, 0, 0, 0
        
        if self.use_mediapipe and self.face_detection:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detection_results = self.face_detection.process(rgb_frame)
            
            if detection_results.detections:
                detection = detection_results.detections[0]
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                fw = int(bbox.width * w)
                fh = int(bbox.height * h)
                result["face_detected"] = True
        else:
            # OpenCV Haar Cascade fallback
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(100, 100)
            )
            if len(faces) > 0:
                x, y, fw, fh = faces[0]
                result["face_detected"] = True
        
        if not result["face_detected"]:
            return result
        
        # Clamp coordinates to frame bounds
        x = max(0, x)
        y = max(0, y)
        fw = min(fw, w - x)
        fh = min(fh, h - y)
        
        result["face_bbox"] = (x, y, fw, fh)
        result["face_size_ratio"] = (fw * fh) / (w * h)
        
        # Check if centered (face center within middle 40% of frame)
        face_cx = x + fw // 2
        face_cy = y + fh // 2
        center_margin = 0.3
        result["centered"] = (
            abs(face_cx - w // 2) < w * center_margin and
            abs(face_cy - h // 2) < h * center_margin
        )
        
        # Analyze brightness (in face region)
        if fw > 0 and fh > 0:
            face_roi = frame[y:y+fh, x:x+fw]
            if face_roi.size > 0:
                gray_roi = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
                result["brightness"] = np.mean(gray_roi) / 255.0
                
                # Blur detection using Laplacian variance
                laplacian = cv2.Laplacian(gray_roi, cv2.CV_64F)
                result["blur_score"] = min(laplacian.var() / 500.0, 1.0)
        
        # Get face mesh for head pose estimation (MediaPipe only)
        if self.use_mediapipe and self.face_mesh:
            try:
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mesh_results = self.face_mesh.process(rgb_frame)
                if mesh_results.multi_face_landmarks:
                    landmarks = mesh_results.multi_face_landmarks[0]
                    result["landmarks"] = landmarks
                    
                    # Estimate head pose from key landmarks
                    nose = landmarks.landmark[1]
                    left_eye = landmarks.landmark[33]
                    right_eye = landmarks.landmark[263]
                    
                    # Simple yaw estimation
                    eye_center_x = (left_eye.x + right_eye.x) / 2
                    yaw = (nose.x - eye_center_x) * 100
                    result["head_pose"]["yaw"] = yaw
                    
                    # Simple pitch estimation
                    eye_center_y = (left_eye.y + right_eye.y) / 2
                    pitch = (nose.y - eye_center_y) * 100
                    result["head_pose"]["pitch"] = pitch
            except Exception:
                pass
        
        # Calculate overall quality score
        size_score = min(result["face_size_ratio"] / 0.15, 1.0)
        brightness_score = 1.0 - abs(result["brightness"] - 0.5) * 2
        center_score = 1.0 if result["centered"] else 0.5
        
        result["quality_score"] = (
            size_score * 0.3 +
            brightness_score * 0.2 +
            result["blur_score"] * 0.3 +
            center_score * 0.2
        )
        
        return result
    
    def draw_overlay(
        self,
        frame: np.ndarray,
        analysis: dict,
        instruction: str,
        progress: Tuple[int, int]
    ) -> np.ndarray:
        """Draw capture UI overlay on frame."""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        
        # Draw face guide oval
        center = (w // 2, h // 2 - 30)
        axes = (int(w * 0.18), int(h * 0.28))
        cv2.ellipse(overlay, center, axes, 0, 0, 360, (0, 255, 255), 2)
        
        # Semi-transparent header
        cv2.rectangle(overlay, (0, 0), (w, 80), (40, 40, 40), -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
        
        # Title
        cv2.putText(
            frame, "DATASET CAPTURE",
            (w // 2 - 120, 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2
        )
        
        # Student name
        cv2.putText(
            frame, f"Student: {self.student_name}",
            (20, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1
        )
        
        # Progress
        cv2.putText(
            frame, f"Progress: {progress[0]}/{progress[1]}",
            (w - 180, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1
        )
        
        # Instruction box
        cv2.rectangle(frame, (20, h - 120), (w - 20, h - 70), (50, 50, 50), -1)
        cv2.rectangle(frame, (20, h - 120), (w - 20, h - 70), (0, 255, 255), 2)
        
        # Instruction text (remove emoji for OpenCV compatibility)
        clean_instruction = instruction.encode('ascii', 'ignore').decode()
        cv2.putText(
            frame, clean_instruction,
            (40, h - 85),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
        )
        
        # Quality indicators
        if analysis["face_detected"]:
            bbox = analysis["face_bbox"]
            quality = analysis["quality_score"]
            
            # Face bounding box (color based on quality)
            color = (
                int((1 - quality) * 255),
                int(quality * 255),
                0
            )
            cv2.rectangle(
                frame,
                (bbox[0], bbox[1]),
                (bbox[0] + bbox[2], bbox[1] + bbox[3]),
                color, 2
            )
            
            # Quality bar
            bar_width = 200
            bar_x = w - bar_width - 30
            bar_y = h - 50
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_width, bar_y + 20), (60, 60, 60), -1)
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + int(bar_width * quality), bar_y + 20), color, -1)
            cv2.putText(frame, "Quality", (bar_x, bar_y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            
            # Status indicators
            indicators = [
                ("Size", analysis["face_size_ratio"] > self.min_face_size),
                ("Center", analysis["centered"]),
                ("Light", 0.3 < analysis["brightness"] < 0.8),
                ("Focus", analysis["blur_score"] > 0.3)
            ]
            
            for i, (name, ok) in enumerate(indicators):
                color = (0, 255, 0) if ok else (0, 0, 255)
                symbol = "+" if ok else "x"
                cv2.putText(
                    frame, f"{symbol} {name}",
                    (30, h - 50 + i * 0),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1
                )
            
            # Ready indicator
            if quality >= self.quality_threshold:
                cv2.putText(
                    frame, "READY - Press SPACE",
                    (w // 2 - 100, h - 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
                )
        else:
            # No face detected warning
            cv2.putText(
                frame, "No face detected - Position yourself in frame",
                (w // 2 - 200, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2
            )
        
        # Controls help
        cv2.putText(
            frame, "SPACE=Capture | S=Skip | Q=Quit | A=Auto",
            (20, h - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1
        )
        
        return frame
    
    def save_image(self, frame: np.ndarray, pose: str) -> str:
        """Save captured image to dataset folder."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{pose}_{timestamp}.jpg"
        filepath = self.student_folder / filename
        
        # Save with good quality
        cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        
        return str(filepath)
    
    def get_current_instruction(self) -> dict:
        """Get current capture instruction."""
        if self.current_instruction_idx >= len(self.CAPTURE_SEQUENCE):
            return None
        return self.CAPTURE_SEQUENCE[self.current_instruction_idx]
    
    def advance_instruction(self):
        """Move to next instruction or pose."""
        current = self.get_current_instruction()
        if current is None:
            return
        
        self.captures_in_pose += 1
        self.total_captures += 1
        
        if self.captures_in_pose >= current["count"]:
            self.current_instruction_idx += 1
            self.captures_in_pose = 0
    
    def get_total_required(self) -> int:
        """Get total number of images to capture."""
        return sum(inst["count"] for inst in self.CAPTURE_SEQUENCE)
    
    def collect(
        self,
        name: str,
        target_count: Optional[int] = None,
        auto_capture: bool = False,
        auto_delay: float = 1.5
    ) -> List[str]:
        """
        Run the dataset collection session.
        
        Args:
            name: Student name
            target_count: Optional override for image count
            auto_capture: Enable automatic capture when quality is good
            auto_delay: Delay between auto captures
        
        Returns:
            List of saved image paths
        """
        # Setup
        self.create_student_folder(name)
        if not self.start_camera():
            return []
        
        saved_images = []
        total_target = target_count or self.get_total_required()
        last_auto_capture = 0
        
        print("\n" + "=" * 60)
        print("🎓 DATASET CAPTURE SESSION")
        print("=" * 60)
        print(f"Student: {name}")
        print(f"Target: {total_target} images")
        print(f"Save location: {self.student_folder}")
        print("\nControls:")
        print("  SPACE - Capture image")
        print("  S     - Skip current pose")
        print("  A     - Toggle auto-capture")
        print("  Q     - Quit")
        print("=" * 60 + "\n")
        
        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    print("❌ Failed to read frame")
                    break
                
                # Mirror frame for natural interaction
                frame = cv2.flip(frame, 1)
                
                # Analyze frame
                analysis = self.analyze_frame(frame)
                
                # Get current instruction
                instruction = self.get_current_instruction()
                if instruction is None or self.total_captures >= total_target:
                    print("\n✅ Dataset collection complete!")
                    break
                
                # Draw UI
                display = self.draw_overlay(
                    frame.copy(),
                    analysis,
                    instruction["instruction"],
                    (self.total_captures, total_target)
                )
                
                # Add auto-capture indicator
                if auto_capture:
                    cv2.putText(
                        display, "[AUTO]",
                        (display.shape[1] - 80, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
                    )
                
                cv2.imshow("Dataset Capture", display)
                
                # Auto capture logic
                if (auto_capture and 
                    analysis["quality_score"] >= self.quality_threshold and
                    time.time() - last_auto_capture > auto_delay):
                    
                    filepath = self.save_image(frame, instruction["pose"])
                    saved_images.append(filepath)
                    self.advance_instruction()
                    last_auto_capture = time.time()
                    
                    print(f"📸 Auto-captured: {Path(filepath).name} ({self.total_captures}/{total_target})")
                    
                    # Brief flash effect
                    cv2.imshow("Dataset Capture", np.ones_like(display) * 255)
                    cv2.waitKey(100)
                    continue
                
                # Handle key input
                key = cv2.waitKey(1) & 0xFF
                
                if key == ord('q'):
                    print("\n⚠️ Collection cancelled by user")
                    break
                
                elif key == ord(' '):  # Space - manual capture
                    if analysis["face_detected"]:
                        filepath = self.save_image(frame, instruction["pose"])
                        saved_images.append(filepath)
                        self.advance_instruction()
                        
                        print(f"📸 Captured: {Path(filepath).name} ({self.total_captures}/{total_target})")
                        
                        # Brief flash
                        cv2.imshow("Dataset Capture", np.ones_like(display) * 255)
                        cv2.waitKey(100)
                    else:
                        print("⚠️ No face detected - cannot capture")
                
                elif key == ord('s'):  # Skip pose
                    self.current_instruction_idx += 1
                    self.captures_in_pose = 0
                    print(f"⏭️ Skipped pose")
                
                elif key == ord('a'):  # Toggle auto
                    auto_capture = not auto_capture
                    print(f"🔄 Auto-capture: {'ON' if auto_capture else 'OFF'}")
        
        finally:
            self.stop_camera()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 CAPTURE SUMMARY")
        print("=" * 60)
        print(f"Student: {name}")
        print(f"Images captured: {len(saved_images)}")
        print(f"Save location: {self.student_folder}")
        
        if saved_images:
            print("\nCaptured files:")
            for path in saved_images[-5:]:  # Show last 5
                print(f"  - {Path(path).name}")
            if len(saved_images) > 5:
                print(f"  ... and {len(saved_images) - 5} more")
        
        print("=" * 60)
        
        return saved_images


def main():
    """Main entry point for dataset collection."""
    parser = argparse.ArgumentParser(
        description="🎓 Automatic Dataset Capture Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python collect_dataset.py --name "John Doe"
  python collect_dataset.py --name "Jane Smith" --count 30 --auto

Dataset Collection Tips:
  - Face should fill 15-30% of the frame
  - Ensure good, even lighting
  - Remove glasses/masks during capture
  - Follow on-screen pose instructions
  - Capture in different lighting conditions
        """
    )
    
    parser.add_argument(
        "--name", "-n",
        required=True,
        help="Student name (will create folder in dataset/)"
    )
    
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=None,
        help="Number of images to capture (default: 20)"
    )
    
    parser.add_argument(
        "--camera", "-cam",
        type=int,
        default=0,
        help="Camera device ID (default: 0)"
    )
    
    parser.add_argument(
        "--auto", "-a",
        action="store_true",
        help="Enable auto-capture mode"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="dataset",
        help="Dataset output directory (default: dataset/)"
    )
    
    args = parser.parse_args()
    
    # Create and run collector
    collector = DatasetCollector(
        dataset_path=args.output,
        camera_id=args.camera
    )
    
    saved = collector.collect(
        name=args.name,
        target_count=args.count,
        auto_capture=args.auto
    )
    
    if saved:
        print(f"\n✅ Successfully captured {len(saved)} images for '{args.name}'")
        print(f"📁 Images saved to: {collector.student_folder}")
        print("\n💡 Next step: Run 'python main.py --encode' to encode the dataset")
    else:
        print("\n⚠️ No images were captured")
    
    return 0 if saved else 1


if __name__ == "__main__":
    exit(main())
