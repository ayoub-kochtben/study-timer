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
from typing import List, Optional, Tuple

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

# Couleurs BGR pour le mode debug.
_COLOR_FACE = (0, 255, 0)        # vert
_COLOR_PHONE = (0, 0, 255)       # rouge
_COLOR_HAND = (0, 165, 255)      # orange


@dataclass
class FrameResult:
    """Résultat complet d'une image : moteur + détails pour l'affichage debug.

    visage, téléphones et mains sont détectés et rapportés séparément.
    """

    observation: Observation
    face_found: bool = False
    face_score: float = 0.0
    face_box: Optional[Tuple[int, int, int, int]] = None
    phone_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    hand_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)


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


def select_face(detections, width: int, height: int, min_confidence: float,
                min_box_fraction: float) -> Optional[Tuple[int, int, int, int]]:
    """Choisit la meilleure détection de visage parmi celles du détecteur.

    Une détection n'est retenue que si :
    - sa confiance atteint `min_confidence` ;
    - sa boîte couvre au moins `min_box_fraction` de la largeur ET de la
      hauteur de l'image (un "visage" minuscule = objet confondu).

    Retourne la boîte en pixels (x1, y1, x2, y2) ou None.
    """
    best = None
    best_score = 0.0
    for detection in detections:
        categories = getattr(detection, "categories", [])
        score = categories[0].score if categories else 0.0
        if score < min_confidence:
            continue
        box = detection.bounding_box
        if box.width < min_box_fraction * width:
            continue
        if box.height < min_box_fraction * height:
            continue
        if score > best_score:
            best = detection
            best_score = score
    if best is None:
        return None
    bb = best.bounding_box
    return (bb.origin_x, bb.origin_y, bb.origin_x + bb.width, bb.origin_y + bb.height)


def _bounding_box(points) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


def debug_draw(frame, result: FrameResult):
    """Dessine sur une copie de l'image les boîtes de chaque détection.

    Vert = visage, rouge = téléphone, orange = main. Utilisé uniquement
    par la fenêtre « Voir la caméra » ; jamais appelé en usage normal.
    """
    shown = frame.copy()
    if result.face_box is not None:
        _draw_labeled_box(shown, result.face_box, _COLOR_FACE, "visage")
    for box in result.phone_boxes:
        _draw_labeled_box(shown, box, _COLOR_PHONE, "telephone")
    for box in result.hand_boxes:
        _draw_labeled_box(shown, box, _COLOR_HAND, "main")
    return shown


def _draw_labeled_box(frame, box, color, label: str) -> None:
    x1, y1, x2, y2 = (int(v) for v in box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(
        frame, label, (x1, max(12, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
        0.5, color, 1, cv2.LINE_AA,
    )


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
        face_box = select_face(
            face_result.detections,
            width,
            height,
            self.config["face_min_confidence"],
            self.config["face_min_box_fraction"],
        )
        face_found = face_box is not None
        face_score = (
            face_result.detections[0].categories[0].score
            if face_result.detections
            else 0.0
        )

        hand_result = self._hand_landmarker.detect_for_video(mp_image, timestamp_ms)
        # hand_landmarks est une liste de mains, chaque main étant déjà une
        # liste de 21 points normalisés (pas d'attribut .landmarks ici).
        hands_px = [
            _landmarks_to_pixels(hand, width, height)
            for hand in hand_result.hand_landmarks
        ]
        hand_boxes = [_bounding_box(points) for points in hands_px]

        # Objets de la liste noire (téléphone au départ), détectés séparément
        # du visage : interdits uniquement s'ils sont tenus en main.
        phone_boxes: List[Tuple[int, int, int, int]] = []
        if self.target_class_ids:
            predictions = self.yolo.predict(
                frame_bgr,
                conf=self.config["yolo_confidence"],
                classes=self.target_class_ids,
                verbose=False,
            )
            for result in predictions:
                for xyxy in result.boxes.xyxy.cpu().numpy():
                    box = tuple(int(v) for v in xyxy)
                    phone_boxes.append(box)

        forbidden = any(
            self._held_in_hand(box, hands_px, width, height) for box in phone_boxes
        )
        observation = Observation(
            face_found=face_found,
            forbidden_in_hand=forbidden,
            timestamp=timestamp,
        )
        return FrameResult(
            observation=observation,
            face_found=face_found,
            face_score=face_score,
            face_box=face_box,
            phone_boxes=phone_boxes,
            hand_boxes=hand_boxes,
        )

    # ------------------------------------------------------------------ #
    def _held_in_hand(self, box, hands_px, width: int, height: int) -> bool:
        margin = self.config["hand_overlap_margin"]
        threshold = self.config["hand_overlap_threshold"]
        expanded = _expanded_box(box, margin, width, height)
        return any(
            _coverage_ratio(points, expanded) >= threshold for points in hands_px
        )
