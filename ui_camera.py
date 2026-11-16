"""Fenêtre « Voir la caméra » : flux en direct + boîtes de détection.

Ce que montre la fenêtre :
- l'image de la webcam avec, en cadres : visage (vert), téléphone (rouge),
  mains (orange) — dessinés par detection.debug_draw ;
- une bordure VERTe quand le comptage est actif, ROUGE sinon, avec la
  raison en haut (« Aucun visage détecté », « Objet interdit en main »).

Rien n'est jamais sauvegardé : l'image reste en mémoire juste le temps
d'être affichée. Fenêtre purement réceptrice : elle est pilotée par les
mêmes signaux que le widget principal.
"""

import cv2
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

_GREEN = "#31c48d"
_RED = "#e02424"


class CameraViewWindow(QWidget):
    # Émis quand l'utilisateur ferme la fenêtre par sa croix, pour que
    # main.py décoche le bouton et coupe le transfert d'images.
    window_closed = pyqtSignal()

    def __init__(self):
        super().__init__(None)  # fenêtre séparée, comme les statistiques
        self.setWindowTitle("Study Timer — Caméra")
        self.resize(660, 550)

        layout = QVBoxLayout(self)
        self._reason_label = QLabel("")
        self._reason_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reason_label.setStyleSheet(
            "color: #f0f0f0; font-size: 15px; font-weight: 600; padding: 4px;"
        )
        layout.addWidget(self._reason_label)

        self._video_label = QLabel()
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._video_label.setMinimumSize(640, 480)
        layout.addWidget(self._video_label, stretch=1)

        # État initial : pas encore d'image tant que la surveillance n'a
        # pas démarré (le flux vient du thread d'analyse).
        self._reason_label.setText("Démarrez la surveillance pour afficher la caméra")

    # ------------------------------------------------------------------ #
    def on_analysis(self, update) -> None:
        """Passe par le signal analysis_received (thread d'analyse → Qt)."""
        frame = getattr(update, "frame", None)
        if frame is None:
            return

        from detection import debug_draw

        shown = debug_draw(frame, update.result)
        height, width = shown.shape[:2]
        rgb = cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888)
        self._video_label.setPixmap(
            QPixmap.fromImage(image).scaled(
                self._video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        if update.state.counting:
            self._video_label.setStyleSheet(f"border: 5px solid {_GREEN};")
            self._reason_label.setText("Étude en cours")
            self._reason_label.setStyleSheet(
                "color: #31c48d; font-size: 15px; font-weight: 600; padding: 4px;"
            )
        else:
            self._video_label.setStyleSheet(f"border: 5px solid {_RED};")
            text = update.state.reason.value if update.state.reason else "Ne compte pas"
            self._reason_label.setText(text)
            self._reason_label.setStyleSheet(
                "color: #e02424; font-size: 15px; font-weight: 600; padding: 4px;"
            )

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:
        self.window_closed.emit()
        super().closeEvent(event)
