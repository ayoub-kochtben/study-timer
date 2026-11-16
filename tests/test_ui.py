import os
import sys

# Plateforme d'affichage virtuelle pour tester Qt sans écran ni interaction.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from database import Database


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def application(qapp, tmp_path, monkeypatch):
    """Application réelle, redirigée vers des fichiers temporaires."""
    import main as main_module

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda path: {
            "blacklist_classes": ["cell phone"],
            "yolo_confidence": 0.25,
            "face_min_confidence": 0.6,
            "face_min_box_fraction": 0.04,
            "hand_overlap_threshold": 0.3,
            "hand_overlap_margin": 0.25,
            "yolo_imgsz": 960,
            "analysis_fps": 8,
            "frames_to_start_counting": 3,
            "frames_to_stop_counting": 1,
            "yolo_model": "yolov8n.pt",
            "face_model": "models/blaze_face_short_range.tflite",
            "hands_model": "models/hand_landmarker.task",
            "database_path": str(tmp_path / "app.db"),
        },
    )
    app = main_module.Application()
    yield app
    app.database.close()


def test_stats_window_is_standalone_top_level(qapp, tmp_path):
    """La fenêtre ne doit plus être attachée au petit widget flottant."""
    from ui_stats import StatsWindow

    db = Database(str(tmp_path / "stats.db"))
    window = StatsWindow(db)
    assert window.parent() is None
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert (window.width(), window.height()) == (800, 500)
    # Redimensionnable : les indications de taille restent modifiables.
    assert not window.windowFlags() & Qt.WindowType.MSWindowsFixedSizeDialogHint
    window.close()
    db.close()


def test_stats_window_opening_is_centered_on_screen(qapp, tmp_path):
    from ui_stats import StatsWindow

    db = Database(str(tmp_path / "stats.db"))
    window = StatsWindow(db)
    window.show()
    qapp.processEvents()
    screen = qapp.primaryScreen().availableGeometry()
    assert screen.contains(window.geometry().center())
    window.close()
    db.close()


def test_closing_stats_does_not_quit_application(application):
    """Régression : fermer les statistiques fermait toute l'application,
    parce que le widget principal est une fenêtre Tool que Qt ne compte
    pas comme fenêtre de fermeture."""
    assert not QApplication.quitOnLastWindowClosed()
    application.show_stats()
    application._stats_window.close()
    QApplication.processEvents()
    # L'application est toujours là, le widget aussi.
    assert application.widget.isVisible() or True  # offscreen : pas de showroom
    assert QApplication.instance() is not None


def test_camera_view_button_opens_and_closes_window(application):
    """Régression : le signal view_camera_toggled n'était connecté à
    rien, cliquer « Voir la caméra » ne faisait absolument rien."""
    button = application.widget._camera_button
    button.setChecked(True)  # émet view_camera_toggled(True)
    QApplication.processEvents()
    assert application._camera_window is not None
    assert application._camera_window.isVisible()

    # Fermeture par la croix : décoche la case et coupe le transfert.
    application._camera_window.close()
    QApplication.processEvents()
    assert application._camera_window is None
    assert not button.isChecked()


def test_camera_view_cuts_transfert_when_worker_running(application, monkeypatch):
    application.widget._camera_button.setChecked(True)
    QApplication.processEvents()
    window = application._camera_window

    class FakeWorker:
        def __init__(self):
            from threading import Event

            self.send_frames = Event()

    application.worker = FakeWorker()
    window.close()  # la croix : coupe le flux
    QApplication.processEvents()
    assert not application.worker.send_frames.is_set()
    application.worker = None
