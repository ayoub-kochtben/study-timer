"""Détection visage + mains + objets de la liste noire (100 % local).

- Visage  : MediaPipe Face Detector ( modèle BlazeFace short range) ;
- Mains   : MediaPipe Hand Landmarker (21 points par main) ;
- Objets  : YOLOv8n (Ultralytics), classes filtrées par la liste noire.

"Objet interdit en main" : suffisamment de points d'une main tombent dans
la boîte YOLO de l'objet (boîte légèrement élargie). Aucune image n'est
jamais écrite sur disque.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Tuple

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from ultralytics import YOLO

from config import load_config
from engine import Observation

_DIR = os.path.dirname(os.path.abspath(__file__))
_MP_IMAGE = mp.Image
_MP_FORMAT = mp.ImageFormat


@dataclass
class FrameResult:
    """Résultat complet d'une image : moteur + détails pour l'affichage."""

    observation: Observation
    face_found: bool = False
    face_score: float = 0.0
    hands_count: int = 0
    forbidden_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)


def _landmarks_to_pixels(landmarks, width: int, height: int):
    return [(lm.x * width, lm.y * height) for lm in landmarks]


def _expanded_box(box, margin: float, width: int, height: int):
    x1, y1, x2, y2 = box
    dx = (x2 - x1) * margin
    dy = (y2 - y1) * margin
    return (
        max(0, x1 - dx), max(0, y1 - dy),
        min(width, x2 + dx), min(height, y2 + dy),
    )


def _coverage_ratio(points, box) -> float:
    """Fraction des points situés dans la boîte (x1, y1, x2, y2)."""
    if not points:
        return 0.0
    x1, y1, x2, y2 = box
    inside = sum(1 for (x, y) in points if x1 <= x <= x2 and y1 <= y <= y2)
    return inside / len(points)


class Detector:
    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        cfg = self.config

        self.yolo = YOLO(os.path.join(_DIR, cfg["yolo_model"]))
        names = self.yolo.names or {}
        self.target_class_ids = [
            cid for cid, name in names.items() if name in cfg["blacklist_classes"]
        ]
        if not self.target_class_ids:
            raise ValueError(
                "Aucune classe de la liste noire "
                f"{cfg['blacklist_classes']} n'est connue du modèle YOLO."
            )

        base = BaseOptions(model_asset_path=os.path.join(_DIR, cfg["face_model"]))
        face_options = mp_vision.FaceDetectorOptions(
            base_options=base,
            running_mode=mp_vision.RunningMode.VIDEO,
            min_detection_confidence=0.5,
        )
        self._face_detector = mp_vision.FaceDetector.create_from_options(face_options)

        base_h = BaseOptions(model_asset_path=os.path.join(_DIR, cfg["hands_model"]))
        hand_options = mp_vision.HandLandmarkerOptions(
            base_options=base_h,
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
        )
        self._hand_landmarker = mp_vision.HandLandmarker.create_from_options(hand_options)

    def close(self) -> None:
        self._face_detector.close()
        self._hand_landmarker.close()

    # ------------------------------------------------------------------ #
    def analyze(self, frame_bgr, timestamp_ms: int, timestamp: datetime) -> FrameResult:
        """Analyse une image OpenCV (BGR).

        timestamp_ms (monotone, croissant strict) sert aux modèles
        MediaPipe en mode VIDEO ; timestamp (horloge murale) alimente
        l'Observation transmise au moteur.
        """
        height, width = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = _MP_IMAGE(image_format=_MP_FORMAT.SRGB, data=rgb)

        face_result = self._face_detector.detect_for_video(mp_image, timestamp_ms)
        face_found = len(face_result.detections) > 0
        face_score = (
            face_result.detections[0].categories[0].score if face_found else 0.0
        )

        hand_result = self._hand_landmarker.detect_for_video(mp_image, timestamp_ms)
        hands_px = [
            _landmarks_to_pixels(h.landmarks, width, height)
            for h in hand_result.hand_landmarks
        ]

        forbidden_boxes: List[Tuple[int, int, int, int]] = []
        if self.target_class_ids:
            predictions = self.yolo.predict(
                frame_bgr,
                conf=self.config["yolo_confidence"],
                classes=self.target_class_ids,
                verbose=False,
            )
            for result in predictions:
                for xyxy in result.boxes.xyxy.cpu().numpy():
                    box = tuple(float(v) for v in xyxy)
                    if self._held_in_hand(box, hands_px, width, height):
                        forbidden_boxes.append(box)

        forbidden = len(forbidden_boxes) > 0
        observation = Observation(
            face_found=face_found,
            forbidden_in_hand=forbidden,
            timestamp=timestamp,
        )
        return FrameResult(
            observation=observation,
            face_found=face_found,
            face_score=face_score,
            hands_count=len(hands_px),
            forbidden_boxes=forbidden_boxes,
        )

    # ------------------------------------------------------------------ #
    def _held_in_hand(self, box, hands_px, width: int, height: int) -> bool:
        margin = self.config["hand_overlap_margin"]
        threshold = self.config["hand_overlap_threshold"]
        expanded = _expanded_box(box, margin, width, height)
        return any(
            _coverage_ratio(points, expanded) >= threshold for points in hands_px
        )
