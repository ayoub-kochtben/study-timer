import os
import sys
import threading
import time
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from camera import AnalysisWorker
from detection import FrameResult
from engine import Observation, StudyEngine


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
