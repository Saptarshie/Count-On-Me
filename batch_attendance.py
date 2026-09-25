"""
CLI for Multi-Image Batch Attendance with Face Deduplication.

Usage:
    python batch_attendance.py <folder_of_images> [--no-csv]

Example:
    python batch_attendance.py classroom_photos/

Outputs a multi-image attendance report and marks identified
students present. No model training involved - uses the existing
pretrained embedding pipeline.

Author: AI Engineer
Version: 1.0.0
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.batch import BatchAttendanceProcessor


def print_report_box(report: dict):
    """Print the ASCII multi-image attendance report."""
    line = "=" * 38
    print()
    print(line)
    print("       MULTI-IMAGE ATTENDANCE")
    print(line)
    print(f"  Images processed:      {report['images_processed']}")
    print(f"  Faces detected:        {report['faces_detected']}")
    print(f"  Unique students:       {report['unique_students']}")
    print(f"  Unique people:         {report['unique_people']}")
    print(f"  Duplicate detections:  {report['duplicates_removed']}")
    print(f"  Unknown faces:         {report['unknown_faces']}")
    print(f"  Avg. match similarity: {report['avg_match_similarity']}")
    print(line)
    print()
    if report['students']:
        print(f"{'Student':<20} {'Present':<8} {'Occ':<5} {'Conf':<6}")
        print("-" * 41)
        for s in report['students']:
            print(f"{s['name']:<20} {'YES':<8} {s['occurrences']:<5} {s['confidence']:<6}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Multi-image attendance with face deduplication"
    )
    parser.add_argument('folder', help='Folder containing classroom images')
    parser.add_argument('--no-csv', action='store_true',
                        help='Skip CSV report export')
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        print(f"Error: folder not found: {folder}")
        sys.exit(1)

    print(f"Processing images in: {folder}")
    processor = BatchAttendanceProcessor()

    def progress(cur, total, name):
        print(f"  [{cur}/{total}] {name}")

    report = processor.process_folder(folder, progress_callback=progress)

    if 'error' in report:
        print(f"Error: {report['error']}")
        sys.exit(1)

    print_report_box(report)

    if not args.no_csv:
        csv_path = processor.export_csv(report=report)
        if csv_path:
            print(f"CSV report: {csv_path}")


if __name__ == '__main__':
    main()