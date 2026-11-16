"""Point d'entrée du Study Timer.

Câble : interface (thread Qt) ↔ worker d'analyse (thread Python)
↔ moteur (pur) ↔ base SQLite. Aucune image n'est écrite sur disque :
seuls les intervalles de temps vont dans la base.
"""

import os
import sys
import threading
from datetime import date, datetime

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from camera import AnalysisWorker
from config import load_config
from database import Database
from detection import Detector
from engine import StudyEngine
from ui_stats import StatsWindow
from ui_widget import StudyWidget

_DIR = os.path.dirname(os.path.abspath(__file__))


class ErrorRelay(QObject):
    """Pont signalé : reçoit les erreurs du thread d'analyse (hors Qt)."""

    error_occurred = pyqtSignal(str)


class Application:
    def __init__(self):
        self.config = load_config(os.path.join(_DIR, "config.json"))
        self.database = Database(os.path.join(_DIR, self.config["database_path"]))
        self.detector: Detector | None = None
        self.worker: AnalysisWorker | None = None
        self.relay = ErrorRelay()
        self.relay.error_occurred.connect(self._on_worker_error)

        self.widget = StudyWidget()
        self.widget.start_clicked.connect(self.toggle_monitoring)
        self.widget.stats_clicked.connect(self.show_stats)
        self.widget.quit_clicked.connect(self.quit)
        self.widget.set_today_base(self.database.seconds_for_day(date.today()))
        self._stats_window: StatsWindow | None = None

    # ------------------------------------------------------------------ #
    # Démarrage / arrêt de la surveillance
    # ------------------------------------------------------------------ #
    def toggle_monitoring(self):
        if self.worker is None:
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def _start_monitoring(self):
        self.widget.set_running(True)
        self.widget.set_status("Chargement des modèles…")
        self.widget.set_buttons_enabled(False)

        def setup():
            try:
                detector = Detector(self.config)
                engine = StudyEngine(
                    frames_to_change_state=self.config["frames_to_change_state"],
                    on_interval=self.database.insert_interval,
                )
                engine.start(datetime.now())
                worker = AnalysisWorker(
                    camera_index=0,
                    detector=detector,
                    engine=engine,
                    on_update=self.widget.on_analysis,
                    on_error=self.relay.error_occurred.emit,
                    analysis_fps=self.config["analysis_fps"],
                )
            except Exception as error:  # modèles absents, fichier corrompu…
                self._setup_failed(str(error))
                return
            # L'ouverture réelle de la caméra a lieu dans worker.run().
            self.detector = detector
            self.worker = worker
            worker.start()
            self.widget.set_buttons_enabled(True)

        threading.Thread(target=setup, daemon=True).start()

    def _setup_failed(self, message: str):
        # Exécuté hors thread Qt : on repasse par des signaux/JSafe appels.
        self.widget.on_setup_failed(message)

    def _stop_monitoring(self):
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.engine.stop(datetime.now())  # clôture l'intervalle en cours
            worker.stop()
            if self.detector is not None:
                self.detector.close()
                self.detector = None
        self.widget.set_running(False)
        self.widget.set_buttons_enabled(True)
        self.widget.set_today_base(self.database.seconds_for_day(date.today()))

    def _on_worker_error(self, message: str):
        self._stop_monitoring()
        QMessageBox.critical(self.widget, "Study Timer", message)

    def show_stats(self):
        if self._stats_window is None:
            self._stats_window = StatsWindow(self.database)
        self._stats_window.refresh()
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    # ------------------------------------------------------------------ #
    def quit(self):
        self._stop_monitoring()
        self.widget.close()

    def run(self):
        self.widget.show()
        self.widget.move(60, 60)


def main():
    app = QApplication(sys.argv)
    application = Application()
    application.run()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
