import os
import sys

# Plateforme d'affichage virtuelle pour tester Qt sans écran ni interaction.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from database import Database


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_stats_window(tmp_path):
    from ui_stats import StatsWindow

    db = Database(str(tmp_path / "stats.db"))
    window = StatsWindow(db)
    return window, db


def test_stats_window_is_standalone_top_level(qapp, tmp_path):
    """La fenêtre ne doit plus être attachée au petit widget flottant."""
    window, db = make_stats_window(tmp_path)
    assert window.parent() is None
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    window.close()
    db.close()


def test_stats_window_opens_at_800x500(qapp, tmp_path):
    window, db = make_stats_window(tmp_path)
    assert (window.width(), window.height()) == (800, 500)
    # Redimensionnable : les indications de taille restent modifiables.
    assert not window.windowFlags() & Qt.WindowType.MSWindowsFixedSizeDialogHint
    window.close()
    db.close()


def test_stats_window_opening_is_centered_on_screen(qapp, tmp_path):
    window, db = make_stats_window(tmp_path)
    window.show()
    qapp.processEvents()
    screen = qapp.primaryScreen().availableGeometry()
    assert screen.contains(window.geometry().center())
    window.close()
    db.close()
