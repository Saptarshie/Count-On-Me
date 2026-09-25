"""
Multi-Image Batch Attendance with Cross-Image Face Deduplication.

Pipeline:
    folder of images
        -> face detection (per image, one at a time for high-res support)
        -> face embeddings (pretrained model, no training)
        -> cross-image matching (cosine similarity)
        -> identity merge / deduplication
        -> unique student attendance

Author: AI Engineer
Version: 1.0.0
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging
import csv

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from app.detection import FaceDetector, FaceDetection
from app.recognition import FaceEncoder, FaceRecognizer

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp')


@dataclass
class FaceCluster:
    """A deduplicated identity: one cluster = one unique person."""
    cluster_id: str
    label: Optional[str]                       # student name if identified
    embeddings: List[np.ndarray] = field(default_factory=list)
    occurrences: int = 0                        # total detections merged
    similarities: List[float] = field(default_factory=list)
    images: List[str] = field(default_factory=list)

    @property
    def avg_similarity(self) -> float:
        return float(np.mean(self.similarities)) if self.similarities else 0.0

    def to_row(self) -> Tuple[str, str, int, float]:
        name = self.label if self.label else self.cluster_id
        present = "YES" if self.label else "NO"
        return (name, present, self.occurrences, round(self.avg_similarity, 2))


def _cosine(e1: np.ndarray, e2: np.ndarray) -> float:
    """Cosine similarity between two embeddings."""
    n1 = e1 / (np.linalg.norm(e1) + 1e-10)
    n2 = e2 / (np.linalg.norm(e2) + 1e-10)
    return float(np.dot(n1, n2))


class BatchAttendanceProcessor:
    """
    Processes a folder of classroom images, computes embeddings once per
    face, deduplicates identities across images via greedy cosine-similarity
    clustering, and marks attendance for unique identified students.
    """

    def __init__(self, detector: Optional[FaceDetector] = None,
                 recognizer: Optional[FaceRecognizer] = None):
        self.detector = detector or FaceDetector()
        self.recognizer = recognizer or FaceRecognizer()
        self.encoder = self.recognizer.encoder
        self.dedup_threshold = config.batch.dedup_threshold
        self.min_face_size = config.batch.min_face_size

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def process_folder(self, folder: Path, progress_callback=None) -> dict:
        """
        Run the full multi-image attendance pipeline on a folder.

        Args:
            folder: directory containing classroom images
            progress_callback: optional fn(current, total, filename)

        Returns:
            Summary dict with stats, clusters and per-image detail.
        """
        image_files = sorted([
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])[:config.batch.max_images]

        if not image_files:
            return {'error': f'No images found in {folder}'}

        # Stage 1+2: detection + embeddings (image at a time)
        detections: List[dict] = []  # {embedding, image, bbox, conf}
        for i, img_path in enumerate(image_files):
            if progress_callback:
                progress_callback(i + 1, len(image_files), img_path.name)
            detections.extend(self._process_single_image(img_path))

        # Stage 3: cross-image deduplication
        clusters = self._deduplicate(detections)

        # Stage 4: attendance
        self._mark_attendance(clusters)

        return self._build_report(folder, len(image_files), detections, clusters)

    def _process_single_image(self, img_path: Path) -> List[dict]:
        """Detect + embed all faces in one image (high-res safe: one at a time)."""
        try:
            image = cv2.imread(str(img_path))
            if image is None:
                logger.warning(f"Could not read {img_path.name}")
                return []

            faces = self.detector.detect(image)
            results = []
            for det in faces:
                if det.width < self.min_face_size or det.height < self.min_face_size:
                    continue
                face_img = self.detector.extract_face(image, det)
                if face_img is None or face_img.size == 0:
                    continue
                encodings = self.encoder.encode_face(face_img)
                if not encodings:
                    continue
                results.append({
                    'embedding': encodings[0],
                    'image': img_path.name,
                    'bbox': det.bbox,
                    'conf': det.confidence,
                })
            if faces:
                logger.info(f"{img_path.name}: {len(faces)} face(s), "
                             f"{len(results)} embedded")
            return results
        except Exception as e:
            logger.error(f"Error processing {img_path.name}: {e}")
            return []

    def _deduplicate(self, detections: List[dict]) -> List[FaceCluster]:
        """
        Greedy single-pass clustering: each new embedding is merged into the
        first cluster whose best cosine similarity >= dedup_threshold.
        Known students identified against the registered dataset.
        """
        clusters: List[FaceCluster] = []
        unknown_counter = 0

        for det in detections:
            emb = det['embedding']

            # Identify against registered students
            label = None
            if self.recognizer.known_encodings:
                sims = self.recognizer._compute_similarities(emb)
                if len(sims):
                    best = int(np.argmax(sims))
                    if sims[best] >= (1.0 - self.recognizer.threshold):
                        label = self.recognizer.known_names[best]

            # Merge into existing cluster of the same identity
            target = None
            best_sim = -1.0
            for c in clusters:
                if label and c.label == label:
                    target, best_sim = c, 1.0
                    break
                if not label and not c.label:
                    sims = [ _cosine(emb, e) for e in c.embeddings ]
                    s = max(sims) if sims else -1.0
                    if s >= self.dedup_threshold and s > best_sim:
                        target, best_sim = c, s

            if target is not None:
                target.embeddings.append(emb)
                target.occurrences += 1
                if best_sim > 0:
                    target.similarities.append(best_sim)
                target.images.append(det['image'])
            else:
                unknown_counter += 1
                clusters.append(FaceCluster(
                    cluster_id=f"Person_{unknown_counter}",
                    label=label,
                    embeddings=[emb],
                    occurrences=1,
                    similarities=[],
                    images=[det['image']],
                ))

        return clusters

    def _mark_attendance(self, clusters: List[FaceCluster]):
        """Mark attendance in DB for identified clusters (best similarity)."""
        if not config.batch.mark_attendance_in_db:
            return
        try:
            from app.database import DatabaseService
            db = DatabaseService()
            for c in clusters:
                if not c.label:
                    continue
                best_sim = self._best_known_similarity(c)
                if best_sim is None:
                    continue
                db.attendance.mark_attendance(c.label, 0.0)
        except Exception as e:
            logger.error(f"Attendance marking skipped: {e}")

    def _best_known_similarity(self, cluster: FaceCluster) -> Optional[float]:
        best = -1.0
        for emb in cluster.embeddings:
            if self.recognizer.known_encodings:
                sims = self.recognizer._compute_similarities(emb)
                if len(sims):
                    best = max(best, float(np.max(sims)))
        return best if best >= 0 else None

    def _build_report(self, folder: Path, n_images: int,
                      detections: List[dict], clusters: List[FaceCluster]) -> dict:
        faces_detected = len(detections)
        identified = [c for c in clusters if c.label]
        unknown = [c for c in clusters if not c.label]
        all_sims = [s for c in clusters for s in c.similarities]

        report = {
            'folder': str(folder),
            'images_processed': n_images,
            'faces_detected': faces_detected,
            'unique_people': len(clusters),
            'unique_students': len(identified),
            'unknown_faces': len(unknown),
            'duplicates_removed': faces_detected - len(clusters),
            'avg_match_similarity': round(float(np.mean(all_sims)), 2) if all_sims else 0.0,
            'students': [
                {
                    'name': c.label,
                    'present': True,
                    'occurrences': c.occurrences,
                    'confidence': round(self._best_known_similarity(c) or 0.0, 2),
                }
                for c in identified
            ],
            'unknown_details': [
                {
                    'cluster_id': c.cluster_id,
                    'occurrences': c.occurrences,
                    'avg_similarity': round(c.avg_similarity, 2),
                    'images': sorted(set(c.images)),
                }
                for c in unknown
            ],
            'per_image': [
                {'image': det['image'],
                 'bbox': [int(v) for v in det['bbox']],
                 'confidence': round(float(det['conf']), 2)}
                for det in detections
            ],
        }
        return report

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def export_csv(self, clusters: Optional[List[FaceCluster]] = None,
                   report: Optional[dict] = None) -> Optional[str]:
        """Save a deduplication report as CSV. Accepts clusters or a report dict."""
        try:
            export_dir = Path(config.batch.export_dir)
            export_dir.mkdir(parents=True, exist_ok=True)
            csv_path = export_dir / f"attendance_{date.today().isoformat()}.csv"

            rows: List[Tuple[str, str, int, float]] = []
            if report:
                for s in report.get('students', []):
                    rows.append((s['name'], 'YES', s['occurrences'], s['confidence']))
                for u in report.get('unknown_details', []):
                    rows.append((u['cluster_id'], 'NO', u['occurrences'],
                                 u['avg_similarity']))
            elif clusters:
                rows = [c.to_row() for c in clusters]

            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Student', 'Present', 'Occurrences', 'Confidence'])
                writer.writerows(rows)

            logger.info(f"Batch CSV report saved to {csv_path}")
            return str(csv_path)
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            return None