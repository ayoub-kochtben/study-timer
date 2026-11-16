import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from engine import Observation, Reason, StudyEngine

T0 = datetime(2026, 11, 16, 9, 0, 0)


def obs(face=True, forbidden=False, t=None):
    return Observation(face_found=face, forbidden_in_hand=forbidden, timestamp=t or T0)


def make_engine(start=3, stop=1):
    intervals = []
    engine = StudyEngine(
        frames_to_start_counting=start,
        frames_to_stop_counting=stop,
        on_interval=lambda s, e: intervals.append((s, e)),
    )
    engine.start(T0)
    return engine, intervals


# ------------------------------------------------------------------ #
# Démarrage (protégé contre les faux départs)
# ------------------------------------------------------------------ #
def test_not_counting_initially_with_face_missing_reason():
    engine, _ = make_engine()
    state = engine.process(obs(face=False))
    assert state.counting is False
    assert state.reason is Reason.FACE_MISSING


def test_counts_after_n_consecutive_good_frames():
    engine, _ = make_engine(start=3)
    assert engine.process(obs(t=T0)).counting is False
    assert engine.process(obs(t=T0)).counting is False
    state = engine.process(obs(t=T0)).counting
    assert state is True  # 3e bonne image consécutive -> on compte
    assert engine.reason is None


def test_single_good_frame_does_not_start_counting():
    engine, _ = make_engine(start=3)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0))  # interruption : compteur remis à zéro
    engine.process(obs(t=T0))
    engine.process(obs(t=T0))
    engine.process(obs(t=T0))  # il faut bien 3 bonnes images de suite
    assert engine.counting is True


def test_start_boundary_is_the_confirming_frame():
    """Le début d'intervalle = l'horodatage de l'image qui confirme, pas
    celui des images précédentes : aucun temps fictif en début."""
    engine, intervals = make_engine(start=2)
    engine.process(obs(t=T0))
    engine.process(obs(t=T0.replace(second=1)))
    engine.process(obs(t=T0.replace(second=2)))  # déjà en comptage : rien
    assert engine.interval_start == T0.replace(second=1)


# ------------------------------------------------------------------ #
# Arrêt : immédiat par défaut, sans délai ni tolérance (spec)
# ------------------------------------------------------------------ #
def test_single_missing_face_stops_immediately():
    engine, intervals = make_engine(start=1)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0.replace(second=1)))
    assert engine.counting is False
    assert len(intervals) == 1
    assert intervals[0] == (T0, T0.replace(second=1))


def test_phone_in_hand_stops_immediately():
    engine, intervals = make_engine(start=1)
    engine.process(obs(t=T0))
    engine.process(obs(forbidden=True, t=T0.replace(second=1)))
    assert engine.counting is False
    assert intervals == [(T0, T0.replace(second=1))]


def test_custom_stop_threshold_still_supported():
    """Un seuil d'arrêt réglable reste possible (2 images ici)."""
    engine, intervals = make_engine(start=1, stop=2)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0.replace(second=1)))
    assert engine.counting is True          # tolérance d'une image
    engine.process(obs(face=False, t=T0.replace(second=2)))
    assert engine.counting is False
    assert intervals == [(T0, T0.replace(second=2))]


def test_short_phone_glance_breaks_the_interval():
    """Un événement plus court que le délai d'arrêt n'existe plus :
    la moindre image contraire clôt l'intervalle en cours."""
    engine, intervals = make_engine(start=1)
    engine.process(obs(t=T0))
    engine.process(obs(forbidden=True, t=T0.replace(second=1)))   # coupure
    engine.process(obs(t=T0.replace(second=2)))                    # reprise
    assert engine.counting is True
    assert intervals == [(T0, T0.replace(second=1))]
    assert engine.interval_start == T0.replace(second=2)


def test_stop_boundary_is_the_first_bad_frame():
    """Aucun surcompte : avec le seuil par défaut (1), la fin
    d'intervalle est exactement la première image contraire."""
    engine, intervals = make_engine(start=1, stop=1)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0.replace(second=1)))
    engine.process(obs(face=False, t=T0.replace(second=2)))
    assert intervals == [(T0, T0.replace(second=1))]


def test_custom_stop_boundary_is_the_confirming_frame():
    """Avec un seuil d'arrêt supérieur, la borne est la 3e image
    contraire consécutive (celle qui confirme)."""
    engine, intervals = make_engine(start=1, stop=3)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0.replace(second=1)))
    engine.process(obs(face=False, t=T0.replace(second=2)))
    engine.process(obs(face=False, t=T0.replace(second=3)))
    assert intervals == [(T0, T0.replace(second=3))]


def test_phone_in_hand_reports_phone_reason_first():
    engine, _ = make_engine(start=1)
    state = engine.process(obs(face=True, forbidden=True))
    assert state.counting is False
    assert state.reason is Reason.FORBIDDEN_IN_HAND


def test_phone_then_no_face_reason_follows_latest_observation():
    engine, _ = make_engine(start=1)
    engine.process(obs(face=True, forbidden=True))
    state = engine.process(obs(face=False, forbidden=False))
    assert state.reason is Reason.FACE_MISSING


# ------------------------------------------------------------------ #
# stop()/start() utilisateur
# ------------------------------------------------------------------ #
def test_interval_closed_on_stop():
    engine, intervals = make_engine(start=1)
    engine.process(obs(t=T0))
    stop_time = T0 + timedelta(seconds=90)
    engine.stop(stop_time)
    assert engine.counting is False
    assert len(intervals) == 1
    assert intervals[0] == (T0, stop_time)


def test_stop_without_counting_emits_nothing():
    engine, intervals = make_engine(start=1)
    engine.stop(T0)
    assert intervals == []


def test_stop_resets_pending_counts():
    engine, intervals = make_engine(start=2)
    engine.process(obs(t=T0))
    engine.process(obs(face=False, t=T0))  # stoppe l'intervalle le cas échéant
    engine.stop(T0)
    engine.process(obs(t=T0))
    # après stop, une seule bonne image ne doit PAS rouvrir le comptage
    assert engine.counting is False
    assert intervals == []


def test_restart_after_stop_opens_new_interval():
    engine, intervals = make_engine(start=1)
    engine.process(obs(t=T0))
    engine.stop(T0.replace(second=10))
    engine.start(T0.replace(second=15))
    engine.process(obs(t=T0.replace(second=20)))
    engine.stop(T0.replace(second=30))
    assert len(intervals) == 2
    assert intervals[1] == (T0.replace(second=20), T0.replace(second=30))


def test_thresholds_must_be_positive():
    with pytest.raises(ValueError):
        StudyEngine(frames_to_start_counting=0)
    with pytest.raises(ValueError):
        StudyEngine(frames_to_stop_counting=0)
