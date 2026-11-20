import os
import sys
import threading
import time
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from camera import AnalysisWorker
from detection import FrameResult
from engine import Observation, Reason, StudyEngine


def test_stop_while_processing_does_not_corrupt_state():
    """Régression : stop (thread interface) pendant process (thread
    d'analyse) corrompait l'état — le compteur repartait de mal (bug
    « redémarre à 1,36 s »). L'intervalle doit rester cohérent."""
    intervals = []
    T0 = datetime(2026, 11, 17, 9, 0, 0)
    engine = StudyEngine(frames_to_start_counting=1, frames_to_stop_counting=1, on_interval=lambda s, e: intervals.append((s, e)))
    engine.start(T0)

    stopper_hit = threading.Event()
    release = threading.Event()

    original_apply = engine._apply_transition

    def slow_apply(target, now):
        if target and not stopper_hit.is_set():  # première ouverture
            stopper_hit.set()
            release.wait(timeout=5)  # stop() va tenter de passer pendant
        original_apply(target, now)

    engine._apply_transition = slow_apply

    def obs(t):
        return Observation(face_found=True, forbidden_in_hand=False, timestamp=t)

    processor = threading.Thread(target=lambda: engine.process(obs(T0)))
    processor.start()
    stopper_hit.wait(timeout=5)
    stopper = threading.Thread(target=lambda: engine.stop(T0 + timedelta(seconds=10)))
    stopper.start()
    release.set()
    processor.join(timeout=5)
    stopper.join(timeout=5)

    # Invariants après la course : état cohérent, intervalle clôturé
    # une seule fois, jamais à l'envers.
    assert engine.counting is False
    assert engine.interval_start is None
    assert len(intervals) == 1
    assert intervals[0][1] > intervals[0][0]


class FakeCamera:
    """Remplace Camera : renvoie des images numérotées, sans matériel."""

    def __init__(self):
        self.counter = 0

    def read(self):
        self.counter += 1
        # Renvoie l'image seule, comme Camera.read() qui masque VideoCapture.
        return np.full((48, 64, 3), self.counter % 255, dtype=np.uint8)

    def release(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


class FakeDetector:
    def analyze(self, frame, timestamp_ms, timestamp):
        return FrameResult(
            observation=Observation(face_found=True, forbidden_in_hand=False, timestamp=timestamp)
        )


def run_worker(collected, enable_frames_at_start):
    updates = []
    engine = StudyEngine()
    engine.start(datetime.now())
    worker = AnalysisWorker(
        camera_index=0,
        detector=FakeDetector(),
        engine=engine,
        on_update=lambda u: updates.append(u),
        on_error=lambda m: collected.append("erreur: " + m),
        analysis_fps=200,
        camera_factory=lambda index: FakeCamera(),
    )
    if enable_frames_at_start:
        worker.send_frames.set()
    worker.start()
    deadline = time.monotonic() + 5
    while len(updates) < 5 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    return updates


def test_frames_not_sent_when_view_disabled():
    """Option désactivée : aucune image ne transite (économie CPU)."""
    collected = []
    updates = run_worker(collected, enable_frames_at_start=False)
    assert len(updates) >= 5
    assert all(update.frame is None for update in updates)
    assert collected == []


def test_frames_flow_when_view_enabled():
    collected = []
    updates = run_worker(collected, enable_frames_at_start=True)
    assert len(updates) >= 5
    assert all(update.frame is not None for update in updates)
    # Les images sont bien celles de la fausse caméra (contenu variable).
    values = {int(update.frame[0, 0, 0]) for update in updates}
    assert len(values) > 1


def test_activating_frames_mid_flight():
    collected = []
    updates = []
    engine = StudyEngine()
    engine.start(datetime.now())
    worker = AnalysisWorker(
        0, FakeDetector(), engine, lambda u: updates.append(u),
        lambda m: collected.append(m), analysis_fps=200,
        camera_factory=lambda index: FakeCamera(),
    )
    worker.start()
    deadline = time.monotonic() + 5
    while len(updates) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert all(update.frame is None for update in updates)  # d'abord None
    worker.send_frames.set()
    deadline = time.monotonic() + 5
    while not any(update.frame is not None for update in updates):
        if time.monotonic() > deadline:
            break
        time.sleep(0.01)
    worker.stop()
    assert any(update.frame is not None for update in updates)


def test_worker_survives_transient_errors_then_recovers():
    """Une erreur ponctuelle ne doit pas tuer l'analyse."""
    calls = {"n": 0}

    class FlakyDetector:
        def analyze(self, frame, ts, wall):
            calls["n"] += 1
            if calls["n"] in (1, 2, 3):
                raise RuntimeError("raté une fois")
            return FrameResult(
                observation=Observation(face_found=True, forbidden_in_hand=False, timestamp=wall)
            )

    updates = []
    engine = StudyEngine()
    engine.start(datetime.now())
    worker = AnalysisWorker(
        0, FlakyDetector(), engine, lambda u: updates.append(u),
        lambda m: None, analysis_fps=200,
        camera_factory=lambda index: FakeCamera(),
    )
    worker.start()
    deadline = time.monotonic() + 5
    while calls["n"] < 6 and time.monotonic() < deadline:
        time.sleep(0.01)
    worker.stop()
    assert calls["n"] >= 6  # l'analyse a continué après les erreurs
    assert len(updates) >= 3  # et des résultats continuent d'arriver


def test_worker_reports_and_closes_interval_after_persistent_failure():
    """Panne durable : erreur remontée ET intervalle clôturé (pas de
    compteur repris de zéro sans avoir sauvegardé le temps écoulé)."""
    intervals = []
    engine = StudyEngine(on_interval=lambda s, e: intervals.append((s, e)))
    engine.start(datetime.now())

    class BrokenDetector:
        def analyze(self, frame, ts, wall):
            raise RuntimeError("panne durable")

    errors = []
    worker = AnalysisWorker(
        0, BrokenDetector(), engine, lambda u: None,
        errors.append, analysis_fps=200,
        camera_factory=lambda index: FakeCamera(),
    )
    worker.start()
    worker.join(timeout=8)
    assert not worker.is_alive()
    assert errors, "l'erreur doit être remontée à l'interface"
    # Le moteur a fermé l'intervalle ouvert avant la panne (ici aucun,
    # mais stop() ne doit pas lever ni laisser un état incohérent).
    assert engine.counting is False


def test_worker_survives_analyzing_error_and_reports():
    class BrokenDetector:
        def analyze(self, frame, ts, wall):
            raise RuntimeError("panne de test")

    errors = []
    engine = StudyEngine()
    engine.start(datetime.now())
    worker = AnalysisWorker(
        0, BrokenDetector(), engine, lambda u: None,
        errors.append, analysis_fps=200,
        camera_factory=lambda index: FakeCamera(),
    )
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert any("panne de test" in message for message in errors)
