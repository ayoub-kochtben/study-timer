"""Machine à états du compteur d'étude — pure, testable sans caméra.

Règles :
- compter si un visage est détecté ET rien de la liste noire n'est en main ;
- un changement d'état n'est appliqué qu'après `frames_to_change_state`
  observations consécutives allant dans le même sens (anti-clignotement) ;
- chaque période continue de comptage devient un intervalle (début, fin)
  transmis à `on_interval(start, fin)` — rien d'autre n'est stocké.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional
import threading


class Reason(Enum):
    """Pourquoi le chrono ne compte pas (None quand il compte)."""

    FACE_MISSING = "Aucun visage détecté"
    FORBIDDEN_IN_HAND = "Objet interdit en main"


@dataclass
class Observation:
    """Résultat de l'analyse d'une image, par detection.py."""

    face_found: bool
    forbidden_in_hand: bool
    timestamp: datetime


@dataclass
class EngineState:
    counting: bool
    reason: Optional[Reason]          # None si counting est True
    interval_start: Optional[datetime]
    just_changed: bool                # True si l'état vient de basculer


class StudyEngine:
    def __init__(
        self,
        frames_to_change_state: int = 3,
        on_interval: Optional[Callable[[datetime, datetime], None]] = None,
    ):
        if frames_to_change_state < 1:
            raise ValueError("frames_to_change_state doit valoir au moins 1")
        self.frames_to_change_state = frames_to_change_state
        self.on_interval = on_interval
        # Verrou unique : process() (thread d'analyse) et stop()/start()
        # (thread de l'interface) ne doivent jamais s'entremêler, sinon
        # un intervalle peut être clôturé deux fois ou avec une borne
        # incohérente — et le compteur repart de mal à la reprise.
        self._lock = threading.Lock()
        self.counting = False
        self.reason: Optional[Reason] = None
        self.interval_start: Optional[datetime] = None
        self._pending_counting: Optional[bool] = None
        self._pending_count = 0

    # ------------------------------------------------------------------ #
    def process(self, obs: Observation) -> EngineState:
        """Avance la machine avec le résultat d'une image analysée."""
        with self._lock:
            should_count = obs.face_found and not obs.forbidden_in_hand
            self.reason = None if should_count else self._blocking_reason(obs)

            if should_count != self._pending_counting:
                self._pending_counting = should_count
                self._pending_count = 1
            else:
                self._pending_count += 1

            changed = False
            if self._pending_count >= self.frames_to_change_state and should_count != self.counting:
                self._apply_transition(should_count, obs.timestamp)
                changed = True

            return EngineState(self.counting, self.reason, self.interval_start, changed)

    # ------------------------------------------------------------------ #
    def start(self, now: datetime) -> None:
        """Démarre la surveillance (aucun intervalle ouvert tant que les
        conditions ne sont pas réunies)."""
        with self._lock:
            self.counting = False
            self.interval_start = None
            self._pending_counting = None
            self._pending_count = 0
            self.reason = Reason.FACE_MISSING

    def stop(self, now: datetime) -> None:
        """Arrêt demandé par l'utilisateur : clôture l'intervalle en cours."""
        with self._lock:
            self._close_interval(now)
            self.counting = False
            self.interval_start = None
            self._pending_counting = None
            self._pending_count = 0
            self.reason = Reason.FACE_MISSING

    # ------------------------------------------------------------------ #
    def _blocking_reason(self, obs: Observation) -> Reason:
        if obs.forbidden_in_hand:
            return Reason.FORBIDDEN_IN_HAND
        return Reason.FACE_MISSING

    def _apply_transition(self, target: bool, now: datetime) -> None:
        if target:
            self.counting = True
            self.interval_start = now
        else:
            self._close_interval(now)
            self.counting = False
            self.interval_start = None

    def _close_interval(self, now: datetime) -> None:
        if self.counting and self.interval_start is not None and self.on_interval:
            self.on_interval(self.interval_start, now)
