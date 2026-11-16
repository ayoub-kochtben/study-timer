"""Fenêtre statistiques : graphiques jour / semaine / mois + série en cours."""

import os
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import Database

_LIGHT_BG = "#2b2b33"
_ACCENT = "#7aa2f7"


def _fmt_hm(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h} h {m:02d}"
    return f"{m} min"


class StatsWindow(QWidget):
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
            ["30 derniers jours", "12 dernières semaines", "12 derniers mois"]
        )
        self._range_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self._range_combo)
        top.addStretch()
        close_button = QPushButton("Fermer")
        close_button.clicked.connect(self.close)
        top.addWidget(close_button)
        layout.addLayout(top)

        self._figure = Figure(figsize=(8, 4), dpi=100)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas, stretch=1)

        self._streak_label = QLabel()
        self._streak_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(self._streak_label)

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

    def refresh(self):
        mode = self._range_combo.currentIndex()
        today = date.today()
        if mode == 0:
            first = today - timedelta(days=29)
            data = self._database.daily_seconds(first, today)
            labels = [d.strftime("%d/%m") for d, _ in data]
            values = [s / 3600 for _, s in data]
            title = "Temps d'étude par jour (heures)"
        elif mode == 1:
            # Semaines calées sur lundi.
            monday = today - timedelta(days=today.weekday())
            labels, values = [], []
            for week in range(11, -1, -1):
                week_start = monday - timedelta(weeks=week)
                days = self._database.daily_seconds(
                    week_start, week_start + timedelta(days=6)
                )
                labels.append(week_start.strftime("S %d/%m"))
                values.append(sum(s for _, s in days) / 3600)
            title = "Temps d'étude par semaine (heures)"
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
                days = self._database.daily_seconds(month, last_day)
                labels.append(month.strftime("%m/%Y"))
                values.append(sum(s for _, s in days) / 3600)
            title = "Temps d'étude par mois (heures)"

        self._draw_bars(labels, values, title)

        streak = self._database.current_streak(today)
        today_seconds = self._database.seconds_for_day(today)
        self._streak_label.setText(
            f"Série en cours : {streak} jour(s) consécutif(s) — "
            f"aujourd'hui : {_fmt_hm(today_seconds)}"
        )

    # ------------------------------------------------------------------ #
    def _draw_bars(self, labels, values, title):
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
        for index, value in enumerate(values):
            if value > 0:
                axes.text(
                    index, value, _fmt_hm(value * 3600),
                    ha="center", va="bottom", fontsize=7, color="#f0f0f0",
                )
        self._figure.tight_layout()
        self._canvas.draw()
