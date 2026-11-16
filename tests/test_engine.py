import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import Observation, Reason, StudyEngine

T0 = datetime(2026, 11, 16, 9, 0, 0)


def obs(face=True, forbidden=False, t=None):
    return Observation(face_found=face, forbidden_in_hand=forbidden, timestamp=t or T0)


def make_engine(n=3):
    intervals = []
    engine = StudyEngine(frames_to_change_state=n, on_interval=lambda s, e: intervals.append((s, e)))
    engine.start(T0)
    return engine, intervals


def test_not_counting_initially_with_face_missing_reason():
    engine, _ = make_engine()
    state = engine.process(obs(face=False))
    assert state.counting is False
    assert state.reason is Reason.FACE_MISSING


def test_counts_after_n_consecutive_good_frames():
    engine, _ = make_engine(n=3)
    assert engine.process(obs(t=T0)).counting is False
    assert engine.process(obs(t=T0)).counting is False
    state = engine.process(obs(t=T0)).counting
    assert state is True  # 3e bonne image consécutive -> on compte
    assert engine.reason is None


def test_single_good_frame_does_not_start_counting():
    engine, _ = make_engine(n=3)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0))  # interruption : compteur remis à zéro
    engine.process(obs(t=T0))
    engine.process(obs(t=T0))
    assert engine.process(obs(t=T0))  # il faut bien 3 bonnes images de suite


def test_face_missing_stops_after_n_consecutive_bad_frames():
    engine, intervals = make_engine(n=2)
    engine.process(obs(t=T0))
    engine.process(obs(t=T0))  # compte à partir de T0
    start = engine.interval_start
    engine.process(obs(face=False, t=T0))
    engine.process(obs(face=False, t=T0.replace(second=2)))
    assert engine.counting is False
    assert len(intervals) == 1
    assert intervals[0] == (start, T0.replace(second=2))


def test_single_missing_face_does_not_stop_counting():
    engine, intervals = make_engine(n=3)
    for _ in range(3):
        engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0))  # une seule image manquée : tolérée
    assert engine.counting is True
    assert intervals == []


def test_phone_in_hand_reports_phone_reason_first():
    engine, _ = make_engine(n=1)
    state = engine.process(obs(face=True, forbidden=True))
    assert state.counting is False
    assert state.reason is Reason.FORBIDDEN_IN_HAND


def test_phone_then_no_face_reason_follows_latest_observation():
    engine, _ = make_engine(n=1)
    engine.process(obs(face=True, forbidden=True))
    state = engine.process(obs(face=False, forbidden=False))
    assert state.reason is Reason.FACE_MISSING


def test_interval_closed_on_stop():
    from datetime import timedelta

    engine, intervals = make_engine(n=1)
    engine.process(obs(t=T0))
    stop_time = T0 + timedelta(seconds=90)
    engine.stop(stop_time)
    assert engine.counting is False
    assert len(intervals) == 1
    assert intervals[0] == (T0, stop_time)


def test_stop_without_counting_emits_nothing():
    engine, intervals = make_engine(n=1)
    engine.stop(T0)
    assert intervals == []


def test_stop_resets_pending_counts():
    engine, intervals = make_engine(n=2)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0))  # 1 image "mauvaise" en attente
    engine.stop(T0)
    engine.process(obs(t=T0))
    # après stop, une seule bonne image ne doit PAS rouvrir le comptage
    assert engine.counting is False
    assert intervals == []


def test_restart_after_stop_opens_new_interval():
    engine, intervals = make_engine(n=1)
    engine.process(obs(t=T0))
    engine.stop(T0.replace(second=10))
    engine.start(T0.replace(second=15))
    engine.process(obs(t=T0.replace(second=20)))
    engine.stop(T0.replace(second=30))
    assert len(intervals) == 2
    assert intervals[1] == (T0.replace(second=20), T0.replace(second=30))
