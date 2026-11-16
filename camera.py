"""Capture webcam + thread d'analyse découplé de l'interface.

Le thread lit la caméra à `analysis_fps`, lance la détection et fait
avancer le moteur (StudyEngine). Les résultats remontent à l'interface
uniquement via des rappels ; l'interface les relaie vers le thread Qt
avec des signaux. Aucune image n'est conservée ni écrite sur disque.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

import cv2

from detection import FrameResult
from engine import EngineState, Observation, StudyEngine


class CameraError(Exception):
    """Caméra inaccessible, avec un message prêt à afficher."""


@dataclass
class AnalysisUpdate:
    """Ce que le thread envoie à l'interface après chaque image analysée.

    `frame` ne contient l'image que lorsque l'affichage « Voir la
    caméra » est actif ; sinon il reste None et l'image est libérée
    immédiatement (aucun coût de copie, aucune écriture disque).
    """

    state: EngineState
    result: FrameResult
    frame: Optional[Any] = None


class Camera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        self._capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self._capture.isOpened():
            raise CameraError(
                f"Impossible d'accéder à la webcam (index {index}).\n"
                "Vérifiez qu'elle est branchée et qu'aucune autre "
                "application ne l'utilise."
            )
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self):
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError(
                "La webcam ne renvoie plus d'image.\n"
                "Elle a peut-être été débranchée ou prise par une autre "
                "application : arrêtez et relancez la surveillance."
            )
        return frame

    def release(self) -> None:
        if self._capture is not None:
            self._capture.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


class AnalysisWorker(threading.Thread):
    """Analyse la webcam en boucle, à cadence fixe, hors thread Qt."""

    def __init__(
        self,
        camera_index: int,
        detector,
        engine: StudyEngine,
        on_update,   # callable(AnalysisUpdate)   — appelé à chaque image
        on_error,    # callable(str)              — appelé une fois en cas de panne
        analysis_fps: float = 8.0,
        camera_factory: Optional[Callable[[int], Any]] = None,
    ):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.detector = detector
        self.engine = engine
        self.on_update = on_update
        self.on_error = on_error
        self._period = 1.0 / max(analysis_fps, 0.5)
        self._stop_event = threading.Event()
        # Activé uniquement pour l'affichage « Voir la caméra ».
        self.send_frames = threading.Event()
        self._camera_factory = camera_factory or (lambda index: Camera(index))

    def run(self) -> None:
        try:
            with self._camera_factory(self.camera_index) as camera:
                self._loop(camera)
        except CameraError as error:
            self.on_error(str(error))
        except Exception as error:  # jamais de crash silencieux du thread
            self.on_error(f"Erreur inattendue dans l'analyse : {error}")

    # Nombre d'erreurs consécutives tolérées avant de déclarer le fil
    # mort (une erreur ponctuelle, ex. image corrompue, ne doit pas
    # arrêter la surveillance).
    MAX_CONSECUTIVE_ERRORS = 5

    def _loop(self, camera: Camera) -> None:
        next_tick = time.monotonic()
        consecutive_errors = 0
        while not self._stop_event.is_set():
            try:
                frame = camera.read()
                now_wall = datetime.now()
                timestamp_ms = int(time.monotonic() * 1000)  # croissant, exigé MediaPipe
                result = self.detector.analyze(frame, timestamp_ms, now_wall)
            except CameraError:
                raise  # panne caméra réelle : arrêt propre via run()
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                    # Le fil meurt : on clôture l'intervalle en cours
                    # pour ne perdre que la petite BUG seconde récente,
                    # puis on remonte l'erreur à l'interface.
                    try:
                        self.engine.stop(datetime.now())
                    except Exception:
                        pass
                    raise
                next_tick += self._period
                delay = next_tick - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.monotonic()
                continue
            consecutive_errors = 0
            state = self.engine.process(result.observation)
            update = AnalysisUpdate(state=state, result=result)
            if self.send_frames.is_set():
                update.frame = frame
            self.on_update(update)

            next_tick += self._period
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()  # on a pris du retard : on repart

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        self.join(timeout=timeout)
