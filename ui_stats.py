"""Fenêtre statistiques : graphiques jour / mois + temps du jour par matière."""

import os
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import Database

_LIGHT_BG = "#2b2b33"
_ACCENT = "#7aa2f7"
_TOTAL = "Global"  # tout le temps du jour, toutes matières confondues


def _fmt_hm(seconds: float) -> str:
    """Durée lisible, à la seconde près : « 9 s », « 2 min 05 s », « 1 h 02 min 05 s »."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min {s:02d} s"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


class StatsWindow(QWidget):
    # L'effacement est fait par main.py (il doit aussi couper la session en cours).
    clear_requested = pyqtSignal()

    def __init__(self, database: Database, parent=None):
        # Toujours une fenêtre indépendante : parentée au petit widget
        # flottant, elle héritait de son rendu compact et restait illisible.
        super().__init__(None)
        self._database = database
        self.setWindowTitle("Study Timer — Statistiques")
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        )
        self.resize(800, 500)
        self._center_on_screen()

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self._range_combo = QComboBox()
        self._range_combo.addItems(
            ["30 derniers jours", "12 derniers mois"]
        )
        self._range_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self._range_combo)
        # Graphique global (toutes matières) ou d'une seule matière.
        self._subject_combo = QComboBox()
        self._subject_combo.currentIndexChanged.connect(self._on_subject_selected)
        top.addWidget(self._subject_combo)
        self._filling_subjects = False
        top.addStretch()
        clear_button = QPushButton("Effacer aujourd'hui")
        clear_button.setToolTip("Efface le temps d'aujourd'hui et toutes les matières")
        clear_button.clicked.connect(self._confirm_clear)
        top.addWidget(clear_button)
        close_button = QPushButton("Fermer")
        close_button.clicked.connect(self.close)
        top.addWidget(close_button)
        layout.addLayout(top)

        self._figure = Figure(figsize=(8, 4), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas, stretch=1)

        self._today_subjects_label = QLabel()
        self._today_subjects_label.setWordWrap(True)
        self._today_subjects_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._today_subjects_label)

        self.refresh()

    # ------------------------------------------------------------------ #
    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.center().y() - self.height() // 2,
        )

    def _confirm_clear(self):
        answer = QMessageBox.question(
            self,
            "Effacer",
            "Effacer tout le temps d'aujourd'hui et toutes les matières "
            "enregistrées ?\n\nCette action est définitive.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_requested.emit()

    def _on_subject_selected(self, _index):
        if not self._filling_subjects:
            self.refresh()

    def _fill_subjects(self):
        """Recharge la liste « Global + matières déjà tapées » sans perdre le choix."""
        current = self._subject_combo.currentText()
        self._filling_subjects = True
        self._subject_combo.clear()
        self._subject_combo.addItem(_TOTAL)
        self._subject_combo.addItems(self._database.subjects())
        index = self._subject_combo.findText(current)
        self._subject_combo.setCurrentIndex(max(index, 0))
        self._filling_subjects = False

    def refresh(self):
        self._fill_subjects()
        chosen = self._subject_combo.currentText()
        if chosen in ("", _TOTAL):
            subject = None           # tout confondu
        else:
            subject = chosen
        scope = chosen or _TOTAL
        mode = self._range_combo.currentIndex()
        today = date.today()
        if mode == 0:
            first = today - timedelta(days=29)
            data = self._database.daily_seconds(first, today, subject)
            labels = [d.strftime("%d/%m") for d, _ in data]
            values = [s for _, s in data]
            title = f"Temps d'étude par jour — {scope}"
        else:
            labels, values = [], []
            months = []
            month = today.replace(day=1)
            for _ in range(12):
                months.append(month)
                month = (month - timedelta(days=1)).replace(day=1)
            for month in reversed(months):
                if month == today.replace(day=1):
                    last_day = today
                else:
                    last_day = (month + timedelta(days=31)).replace(day=1) - timedelta(
                        days=1
                    )
                days = self._database.daily_seconds(month, last_day, subject)
                labels.append(month.strftime("%m/%Y"))
                values.append(sum(s for _, s in days))
            title = f"Temps d'étude par mois — {scope}"

        self._draw_bars(labels, values, title)

        global_today = self._database.seconds_for_day(today)  # tout confondu

        today_by_subject = self._database.seconds_by_subject(today, today)
        if today_by_subject:
            parts = [f"{name} : {_fmt_hm(sec)}" for name, sec in today_by_subject.items()]
        else:
            parts = []
        parts.insert(0, f"Global : {_fmt_hm(global_today)}")
        self._today_subjects_label.setText("Aujourd'hui : " + "  ·  ".join(parts))

    # ------------------------------------------------------------------ #
    def _draw_bars(self, labels, seconds_values, title):
        # Unité de l'axe adaptée : une journée de 40 s reste lisible
        # (en heures elle tomberait à 0,01 et la barre serait invisible).
        peak = max(seconds_values, default=0.0)
        if peak >= 3600:
            divisor, unit_name = 3600, "heures"
        elif peak >= 60:
            divisor, unit_name = 60, "minutes"
        else:
            divisor, unit_name = 1, "secondes"
        values = [value / divisor for value in seconds_values]
        self._figure.clear()
        axes = self._figure.add_subplot(111)
        axes.set_facecolor(_LIGHT_BG)
        self._figure.patch.set_facecolor(_LIGHT_BG)
        axes.bar(labels, values, color=_ACCENT, width=0.65)
        axes.set_title(title, color="#f0f0f0")
        axes.tick_params(colors="#b8b8c2")
        for spine in axes.spines.values():
            spine.set_color("#4a4a58")
        step = max(1, len(labels) // 15)
        axes.set_xticks(range(0, len(labels), step))
        axes.set_xticklabels(labels[::step], rotation=45, ha="right")
        axes.grid(axis="y", color="#4a4a58", alpha=0.4)
        ymax = max(values, default=0.0)
        axes.set_ylim(0, ymax * 1.15 if ymax else 1)
        axes.set_ylabel(unit_name, color="#b8b8c2")
        for index, value in enumerate(values):
            if value > 0:
                axes.text(
                    index, value, _fmt_hm(value * divisor),
                    ha="center", va="bottom", fontsize=7, color="#f0f0f0",
                )
        self._figure.tight_layout()
        self._canvas.draw()
