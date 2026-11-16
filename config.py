"""Configuration du Study Timer.

Les valeurs par défaut vivent ici ; un fichier `config.json` (même dossier)
peut les écraser une par une. La liste noire d'objets (téléphone au départ)
est extensible directement dans ce fichier JSON.
"""

import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_DIR, "config.json")

DEFAULTS = {
    # Classes YOLO interdites : le chrono s'arrête si l'objet est tenu en main.
    # Ajoutez ici tout label COCO (ex. "book", "laptop"...).
    "blacklist_classes": ["cell phone"],
    # Seuil de confiance YOLO pour retenir une détection.
    "yolo_confidence": 0.40,
    # Fraction minimale des points de main MediaPipe devant tomber dans la
    # boîte d'un objet blacklisté pour le considérer "en main".
    "hand_overlap_threshold": 0.30,
    # Marge (en fraction de la taille de la boîte) élargie autour de la boîte
    # YOLO pour le test de chevauchement avec la main.
    "hand_overlap_margin": 0.15,
    # Cadence d'analyse de la webcam (images par seconde).
    "analysis_fps": 8,
    # Anti-clignotement : un changement d'état n'est appliqué qu'après ce
    # nombre d'images consécutives allant dans le même sens.
    "frames_to_change_state": 3,
    # Chemins des modèles (téléchargés une fois, ignorés par git).
    "yolo_model": "yolov8n.pt",
    "face_model": "models/blaze_face_short_range.tflite",
    "hands_model": "models/hand_landmarker.task",
    # Base de données SQLite.
    "database_path": "data/study_timer.db",
}


def load_config(path: str = CONFIG_PATH) -> dict:
    """Charge la config : DEFAULTS, écrasés par config.json s'il existe.

    Si le fichier n'existe pas, il est créé à partir des défauts pour
    servir de point de départ modifiable.
    """
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULTS, f, indent=2, ensure_ascii=False)
        except OSError:
            pass  # lecture seule : on utilise les défauts sans fichier
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            user = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if isinstance(user, dict):
        merged.update({k: v for k, v in user.items() if k in DEFAULTS})
    return merged
