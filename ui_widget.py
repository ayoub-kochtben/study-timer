"""Widget flottant principal : voyant, temps du jour, boutons.

Sans bordure, toujours au premier plan, déplaçable à la souris.
Le widget ne connaît ni la caméra ni la base : il affiche et émet
des signaux ; main.py fait le câblage.
"""

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from engine import EngineState, Reason

_STYLE_BASE = """
#wrapper {{
    background-color: #2b2b33;
    border-radius: 14px;
}}
QLabel {{ color: #f0f0f0; }}
#led {{
    border-radius: 9px;
    background-color: {color};
}}
QPushButton {{
    color: #f0f0f0;
    background-color: #3d3d47;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
}}
 QPushButton:pressed {{ background-color: #57576a; }}
"""


def _fmt_hms(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min {s:02d} s"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class StudyWidget(QWidget):
    # Émis vers main.py (thread Qt) — clics de l'utilisateur.
    start_clicked = pyqtSignal()
    stats_clicked = pyqtSignal()
    quit_clicked = pyqtSignal()
    view_camera_toggled = pyqtSignal(bool)
    # Reçu depuis le thread d'analyse (connexion Qt, marshal automatique).
    analysis_received = pyqtSignal(object)
    setup_failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._state: EngineState | None = None
        self._today_seconds = 0.0  # secondes déjà en base pour aujourd'hui

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        wrapper = QWidget(objectName="wrapper")
        root.addWidget(wrapper)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(16, 12, 16, 14)

        top = QHBoxLayout()
        self._led = QLabel(objectName="led")
        self._led.setFixedSize(18, 18)
        self._status_label = QLabel("Prêt")
        self._status_label.setStyleSheet("color: #b8b8c2;")
        top.addWidget(self._led)
        top.addSpacing(8)
        top.addWidget(self._status_label)
        top.addStretch()
        layout.addLayout(top)

        self._time_label = QLabel("00 s")
        self._time_label.setStyleSheet("font-size: 26px; font-weight: 600;")
        layout.addWidget(self._time_label)

        day_row = QHBoxLayout()
        self._day_label = QLabel("Aujourd'hui : 0 s")
        self._day_label.setStyleSheet("color: #b8b8c2;")
        day_row.addWidget(self._day_label)
        day_row.addStretch()
        layout.addLayout(day_row)

        buttons = QHBoxLayout()
        self._start_button = QPushButton("Démarrer")
        self._stats_button = QPushButton("Statistiques")
        self._camera_button = QPushButton("Voir la caméra")
        self._camera_button.setCheckable(True)
        self._camera_button.setChecked(False)  # désactivé par défaut
        self._camera_button.toggled.connect(self.view_camera_toggled)
        self._quit_button = QPushButton("Quitter")
        self._start_button.clicked.connect(self.start_clicked)
        self._stats_button.clicked.connect(self.stats_clicked)
        self._quit_button.clicked.connect(self.quit_clicked)
        for button in (
            self._start_button, self._stats_button, self._camera_button, self._quit_button
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self._apply_style()
        # Rafraîchit le temps affiché chaque seconde (comptage en cours inclus).
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._update_times)
        self._tick.start(1000)
        self.analysis_received.connect(self._on_analysis_internal)
        self.setup_failed.connect(self._on_setup_failed_internal)

        self._drag_offset = None

    # ------------------------------------------------------------------ #
    # Affichage
    # ------------------------------------------------------------------ #
    def _apply_style(self, running: bool = False):
        color = "#31c48d" if running else "#e02424"
        self.setStyleSheet(_STYLE_BASE.format(color=color))

    def set_today_base(self, seconds: float) -> None:
        """Secondes du jour déjà enregistrées en base (hors session en cours)."""
        self._today_seconds = seconds
        self._update_times()

    def _update_times(self):
        total = self._today_seconds
        state = self._state
        if state is not None and state.counting and state.interval_start:
            total += (datetime.now() - state.interval_start).total_seconds()
        self._time_label.setText(_fmt_hms(total))
        self._day_label.setText(f"Aujourd'hui : {_fmt_hms(total)}")
        if state is not None and state.counting:
            session = 0.0
            if state.interval_start:
                session = (datetime.now() - state.interval_start).total_seconds()
            self._status_label.setText(f"Comptage en cours ({_fmt_hms(session)})")

    def _on_analysis_internal(self, update) -> None:
        self._state = update.state
        self._apply_style(update.state.counting)
        if update.state.counting:
            self._status_label.setText(
                f"Comptage en cours ({_fmt_hms((datetime.now() - update.state.interval_start).total_seconds())})"
            )
        else:
            reason = update.state.reason
            self._status_label.setText(
                reason.value if reason is not None else "Ne compte pas"
            )
        self._update_times()

    # ------------------------------------------------------------------ #
    # Câblage du thread d'analyse (main.py appelle ces deux-là)
    # ------------------------------------------------------------------ #
    def on_analysis(self, update) -> None:
        """Sûr depuis un thread non Qt : passe par un signal."""
        self.analysis_received.emit(update)

    def set_running(self, running: bool) -> None:
        self._start_button.setText("Arrêter" if running else "Démarrer")

    def set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def set_buttons_enabled(self, enabled: bool) -> None:
        self._start_button.setEnabled(enabled)
        self._stats_button.setEnabled(enabled)
        self._camera_button.setEnabled(enabled)
        self._quit_button.setEnabled(enabled)

    def is_camera_view_enabled(self) -> bool:
        return self._camera_button.isChecked()

    def set_camera_button_silently(self, checked: bool) -> None:
        """Change l'état de la case sans émettre view_camera_toggled."""
        self._camera_button.blockSignals(True)
        self._camera_button.setChecked(checked)
        self._camera_button.blockSignals(False)

    def on_setup_failed(self, message: str) -> None:
        """Appelable depuis un thread non Qt."""
        self.setup_failed.emit(message)

    def _on_setup_failed_internal(self, message: str) -> None:
        self._state = None
        self._apply_style(False)
        self.set_running(False)
        self.set_buttons_enabled(True)
        self.set_status("Erreur")
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.critical(self, "Study Timer", message)

    # ------------------------------------------------------------------ #
    # Déplacement du widget
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
