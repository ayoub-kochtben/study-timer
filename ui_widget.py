"""Widget flottant principal : voyant, temps du jour, boutons.

Sans bordure, toujours au premier plan, déplaçable à la souris.
Le widget ne connaît ni la caméra ni la base : il affiche et émet
des signaux ; main.py fait le câblage.
"""

from dataclasses import replace
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import normalize_subject
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
QLineEdit {{
    color: #f0f0f0;
    background-color: #3d3d47;
    border: none;
    border-radius: 8px;
    padding: 5px 10px;
}}
QProgressBar {{
    background-color: #3d3d47;
    border: none;
    border-radius: 5px;
    max-height: 10px;
}}
QProgressBar::chunk {{
    background-color: {goal_color};
    border-radius: 5px;
}}
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
    subject_changed = pyqtSignal(str)  # matière tapée (normalisée, "" = global)
    # Reçu depuis le thread d'analyse (connexion Qt, marshal automatique).
    analysis_received = pyqtSignal(object)
    setup_failed = pyqtSignal(str)

    def __init__(self, daily_goal_hours: float = 3):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._state: EngineState | None = None
        self._today_seconds = 0.0    # total du jour déjà en base (tout confondu)
        self._subject_seconds = 0.0  # déjà en base pour la matière tapée ("" = Global)
        self._goal_seconds = max(float(daily_goal_hours), 0.0) * 3600
        self._running_style = False
        self._goal_was_reached = None
        self._monitoring = False

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

        # Matière tapée librement. Vide = comptage global uniquement.
        self._subject_edit = QLineEdit()
        self._subject_edit.setPlaceholderText("Matière puis Entrée (vide = global)")
        # Validée seulement par Entrée (ou en quittant le champ / Démarrer) :
        # une pause pendant la frappe ne doit pas créer « Meca », « Mecaniq »…
        self._subject_edit.editingFinished.connect(self._emit_subject_if_changed)
        self._emitted_subject = ""
        layout.addWidget(self._subject_edit)

        # Temps global du jour (toutes matières).
        self._time_label = QLabel("00 s")
        self._time_label.setStyleSheet("font-size: 26px; font-weight: 600;")
        layout.addWidget(self._time_label)
        self._total_label = QLabel()
        self._total_label.setStyleSheet("color: #b8b8c2; font-size: 11px;")
        layout.addWidget(self._total_label)

        # Progression de la matière : visible seulement si une matière est tapée.
        self._goal_label = QLabel()
        self._goal_label.setStyleSheet("color: #b8b8c2; font-size: 11px;")
        layout.addWidget(self._goal_label)
        self._goal_bar = QProgressBar()
        self._goal_bar.setRange(0, 1000)
        self._goal_bar.setTextVisible(False)
        layout.addWidget(self._goal_bar)

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
        self._update_times()

    # ------------------------------------------------------------------ #
    # Affichage
    # ------------------------------------------------------------------ #
    def _apply_style(self, running: bool = False):
        color = "#31c48d" if running else "#e02424"
        self._running_style = running
        goal_color = "#f5b942" if self._goal_was_reached else "#7aa2f7"
        self.setStyleSheet(_STYLE_BASE.format(color=color, goal_color=goal_color))

    def _session_seconds(self) -> float:
        state = self._state
        if state is not None and state.counting and state.interval_start:
            return (datetime.now() - state.interval_start).total_seconds()
        return 0.0

    def _update_goal(self) -> None:
        subject = self._emitted_subject
        if not subject or self._goal_seconds <= 0:
            self._goal_bar.hide()
            self._goal_label.hide()
            return
        self._goal_bar.show()
        self._goal_label.show()
        # La session en cours appartient à la matière tapée (figée pendant la session).
        done = self._subject_seconds + self._session_seconds()
        ratio = min(done / self._goal_seconds, 1.0)
        reached = done >= self._goal_seconds
        self._goal_bar.setValue(int(ratio * 1000))
        goal_text = _fmt_hms(self._goal_seconds).replace(" 00 min 00 s", "")
        suffix = " — objectif atteint 🎉" if reached else ""
        self._goal_label.setText(
            f"{subject} : {_fmt_hms(done)} / {goal_text} ({int(ratio * 100)} %){suffix}"
        )
        # La couleur de la barre change quand l'objectif est atteint.
        if reached != self._goal_was_reached:
            self._goal_was_reached = reached
            self._apply_style(self._running_style)

    def current_subject(self) -> str:
        """Matière validée (fin de frappe) ; "" = Global."""
        return self._emitted_subject

    def flush_subject(self) -> None:
        """Valide tout de suite la matière en cours de frappe."""
        self._emit_subject_if_changed()

    def set_today_base(self, seconds: float, subject_seconds: float = 0.0) -> None:
        """Temps du jour déjà en base (global, et pour la matière tapée)."""
        self._today_seconds = seconds
        self._subject_seconds = subject_seconds
        self._update_times()

    def _emit_subject_if_changed(self) -> None:
        subject = normalize_subject(self._subject_edit.text())
        if subject.casefold() != self._emitted_subject.casefold():
            self._emitted_subject = subject
            self.subject_changed.emit(subject)

    def restart_session_at(self, now: datetime) -> None:
        """L'intervalle en cours vient d'être coupé (changement de matière) :
        la session affichée repart de `now` pour ne pas compter deux fois."""
        if self._state is not None and self._state.counting:
            self._state = replace(self._state, interval_start=now)

    def _update_times(self):
        session = self._session_seconds()
        total = self._today_seconds + session
        state = self._state
        # Compteur principal : la matière tapée seule, ou « Global »
        # (= tout le temps du jour) si le champ est vide.
        subject = self._emitted_subject
        if subject:
            self._time_label.setText(
                f"{subject} : {_fmt_hms(self._subject_seconds + session)}"
            )
            self._total_label.setText(f"Global : {_fmt_hms(total)}")
            self._total_label.show()
        else:
            self._time_label.setText(f"Global : {_fmt_hms(total)}")
            self._total_label.hide()
        self._update_goal()
        if state is not None and state.counting:
            session = 0.0
            if state.interval_start:
                session = (datetime.now() - state.interval_start).total_seconds()
            self._status_label.setText(f"Comptage en cours ({_fmt_hms(session)})")

    def _on_analysis_internal(self, update) -> None:
        if not self._monitoring:
            return  # image analysée juste avant l'arrêt : déjà prise en compte
        previous = self._state
        if (
            previous is not None
            and previous.counting
            and previous.interval_start is not None
            and not update.state.counting
        ):
            # La période de comptage vient de se terminer (téléphone, visage
            # perdu…) : elle est enregistrée en base avec cette même borne de
            # fin, on l'ajoute donc au total affiché au lieu de la perdre.
            end = update.result.observation.timestamp
            finished = max((end - previous.interval_start).total_seconds(), 0.0)
            self._today_seconds += finished
            self._subject_seconds += finished
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
        self._monitoring = running
        if not running:
            # Session arrêtée : son temps est en base, main.py recharge le
            # total ; garder l'ancien état le compterait une deuxième fois.
            self._state = None

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
