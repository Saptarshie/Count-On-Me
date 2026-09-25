#!/usr/bin/env python3
"""
Real-Time Classroom Attendance and Student Engagement Tracking System

Main Entry Point

This module serves as the main entry point for the application.
It initializes all components and starts the Flask web server.

Usage:
    python main.py                    # Start web server
    python main.py --encode           # Encode face dataset
    python main.py --cli              # Run in CLI mode (no web interface)
    python main.py --help             # Show help

Author: AI Engineer
Version: 1.0.0
"""

import argparse
import sys
import os
from pathlib import Path

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from config import config
from app.utils import setup_logging, get_logger


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Real-Time Attendance and Engagement Tracking System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    Start the web server
  python main.py --encode           Encode faces from dataset
  python main.py --cli              Run in CLI mode
  python main.py --port 8080        Start server on port 8080
  
Dataset Structure:
  dataset/
    student_name_1/
      img1.jpg
      img2.jpg
    student_name_2/
      img1.jpg
      ...
        """
    )
    
    parser.add_argument(
        '--encode', '-e',
        action='store_true',
        help='Encode faces from the dataset folder'
    )
    
    parser.add_argument(
        '--cli', '-c',
        action='store_true',
        help='Run in CLI mode without web interface'
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default=config.flask.host,
        help=f'Host to bind the server (default: {config.flask.host})'
    )
    
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=config.flask.port,
        help=f'Port to run the server (default: {config.flask.port})'
    )
    
    parser.add_argument(
        '--debug', '-d',
        action='store_true',
        help='Enable debug mode'
    )
    
    parser.add_argument(
        '--camera',
        type=int,
        default=config.camera.camera_index,
        help=f'Camera index to use (default: {config.camera.camera_index})'
    )
    
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'%(prog)s {config.version}'
    )
    
    return parser.parse_args()


def encode_dataset():
    """Encode all faces in the dataset directory."""
    logger = get_logger(__name__)
    
    print("\n" + "="*60)
    print("Face Dataset Encoding")
    print("="*60)
    
    from app.recognition import DatasetEncoder
    
    encoder = DatasetEncoder()
    
    # Check dataset path
    if not config.recognition.dataset_path.exists():
        print(f"\n❌ Dataset path does not exist: {config.recognition.dataset_path}")
        print("Please create the directory and add student folders with images.")
        return False
    
    # Get student directories
    student_dirs = [d for d in config.recognition.dataset_path.iterdir() if d.is_dir()]
    
    if not student_dirs:
        print(f"\n❌ No student folders found in: {config.recognition.dataset_path}")
        print("\nExpected structure:")
        print("  dataset/")
        print("    student_name_1/")
        print("      image1.jpg")
        print("      image2.jpg")
        print("    student_name_2/")
        print("      ...")
        return False
    
    print(f"\n📁 Dataset path: {config.recognition.dataset_path}")
    print(f"👥 Found {len(student_dirs)} student(s)")
    print()
    
    def progress_callback(current, total, name):
        bar_width = 30
        progress = current / total
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)
        print(f"\r[{bar}] {current}/{total} - Encoding: {name}", end="", flush=True)
    
    # Encode
    encoder.encode_dataset(progress_callback=progress_callback)
    print("\n")
    
    # Save
    if encoder.save_encodings():
        print(f"✅ Encodings saved to: {config.recognition.encodings_path}")
        print(f"📊 Total students encoded: {len(encoder.student_encodings)}")
        
        total_encodings = sum(len(s.encodings) for s in encoder.student_encodings.values())
        print(f"📷 Total face encodings: {total_encodings}")
        return True
    else:
        print("❌ Failed to save encodings")
        return False


def run_cli_mode():
    """Run the system in CLI mode (webcam only, no web interface)."""
    logger = get_logger(__name__)
    
    print("\n" + "="*60)
    print("CLI Mode - Real-Time Attendance System")
    print("="*60)
    print("\nPress 'q' to quit, 's' to show stats")
    print()
    
    import cv2
    from app.detection import FaceDetector
    from app.recognition import FaceRecognizer
    from app.engagement import EngagementTracker
    from app.database import DatabaseService
    from app.utils import FPSCounter, draw_text_with_background
    
    # Initialize components
    detector = FaceDetector()
    recognizer = FaceRecognizer()
    tracker = EngagementTracker()
    db_service = DatabaseService()
    fps_counter = FPSCounter()
    
    # Open camera
    cap = cv2.VideoCapture(config.camera.camera_index)
    
    if not cap.isOpened():
        print(f"❌ Could not open camera {config.camera.camera_index}")
        return
    
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.camera.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.camera.frame_height)
    
    print(f"📹 Camera opened: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    print()
    
    attendance_marked = set()
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            
            # Detect faces
            detections = detector.detect(frame)
            
            # Get engagement
            engagement_results = tracker.track(frame)
            
            # Process each face
            for idx, det in enumerate(detections):
                x, y, w, h = det.bbox
                face_img = detector.extract_face(frame, det)
                
                if face_img is not None:
                    result = recognizer.recognize(face_img)
                    
                    if result.is_known:
                        color = (0, 255, 0)
                        name = result.name
                        
                        # Mark attendance
                        if name not in attendance_marked:
                            eng_score = 0
                            if idx < len(engagement_results):
                                _, metrics = engagement_results[idx]
                                eng_score = metrics.engagement_score
                            
                            success, _ = db_service.attendance.mark_attendance(name, eng_score)
                            if success:
                                attendance_marked.add(name)
                                print(f"✅ Attendance marked: {name}")
                    else:
                        color = (0, 0, 255)
                        name = "Unknown"
                    
                    cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                    frame = draw_text_with_background(frame, name, (x, y-10), color=(255,255,255), bg_color=color)
            
            # FPS
            fps = fps_counter.tick()
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"Present: {len(attendance_marked)}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Display
            cv2.imshow('Attendance System', frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                print(f"\n📊 Stats: {len(attendance_marked)} students present")
                
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        detector.release()
        tracker.release()
    
    print(f"\n✅ Session complete. {len(attendance_marked)} students marked present.")


def run_web_server(host: str, port: int, debug: bool):
    """Run the Flask web server."""
    logger = get_logger(__name__)
    
    print("\n" + "="*60)
    print("Real-Time Attendance and Engagement System")
    print("="*60)
    print(f"\n🌐 Starting web server...")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   Debug: {debug}")
    print(f"\n📍 Dashboard URL: http://{host if host != '0.0.0.0' else 'localhost'}:{port}")
    print("\n" + "-"*60)
    
    from app import app, state
    
    # Initialize system
    state.initialize()
    
    # Run Flask
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
        use_reloader=debug
    )


def main():
    """Main entry point."""
    # Setup logging
    setup_logging()
    logger = get_logger(__name__)
    
    # Parse arguments
    args = parse_arguments()
    
    # Update config from args
    if args.camera != config.camera.camera_index:
        config.camera.camera_index = args.camera
    
    # Print banner
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║   Real-Time Classroom Attendance & Engagement System      ║
    ║                                                           ║
    ║   Face Detection • Recognition • Engagement Tracking      ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    try:
        if args.encode:
            # Encode dataset
            success = encode_dataset()
            sys.exit(0 if success else 1)
        
        elif args.cli:
            # CLI mode
            run_cli_mode()
        
        else:
            # Web server mode
            run_web_server(
                host=args.host,
                port=args.port,
                debug=args.debug
            )
            
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error")
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
