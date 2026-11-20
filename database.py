"""Stockage des intervalles d'étude dans SQLite.

On ne stocke JAMAIS d'image ni de vidéo : uniquement des intervalles
(début, fin) en heure locale. Un intervalle à cheval sur minuit est
découpé en un enregistrement par jour calendaire pour que les
statistiques par jour soient exactes.
"""

import os
import sqlite3
from datetime import date, datetime, timedelta

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,   -- ISO local : YYYY-MM-DD HH:MM:SS
    ended_at   TEXT NOT NULL,   -- ISO local : YYYY-MM-DD HH:MM:SS
    seconds    REAL NOT NULL,   -- durée du segment en secondes
    subject    TEXT NOT NULL DEFAULT ''  -- matière choisie dans le widget
);
CREATE INDEX IF NOT EXISTS idx_intervals_started ON intervals(started_at);
"""


def normalize_subject(text: str | None) -> str:
    """Matière tapée par l'utilisateur, nettoyée : espaces superflus
    retirés, première lettre en majuscule (« maths » → « Maths »).
    Chaîne vide = pas de matière (comptage global seulement)."""
    cleaned = " ".join((text or "").split())
    return cleaned[:1].upper() + cleaned[1:]


def _subject_filter(subject: str | None) -> tuple[str, tuple]:
    """Clause SQL optionnelle : None = global (toutes matières)."""
    if subject is None:
        return "", ()
    return " AND subject = ? COLLATE NOCASE", (normalize_subject(subject),)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str):
        self.path = path
        # SQLite ne crée pas les dossiers manquants : on les crée d'abord
        # (ex. "data/" pour data/study_timer.db), sinon OperationalError.
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        # check_same_thread=False : les écritures se font depuis le thread
        # d'analyse, les lectures depuis l'interface. Les transactions sont
        # couvertes par sqlite (GIL) et restent minuscules ici.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript(_SCHEMA)
        # Migration : les bases créées avant l'ajout des matières n'ont
        # pas la colonne `subject` ; on l'ajoute sans toucher aux données.
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(intervals)")}
        if "subject" not in columns:
            self.conn.execute(
                "ALTER TABLE intervals ADD COLUMN subject TEXT NOT NULL DEFAULT ''"
            )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ #
    # Écriture
    # ------------------------------------------------------------------ #
    def insert_interval(self, start: datetime, end: datetime, subject: str = "") -> None:
        """Insère un intervalle d'étude, découpé à chaque passage de minuit."""
        if end <= start:
            return
        subject = normalize_subject(subject)
        cursor = start
        while cursor.date() != end.date():
            next_midnight = datetime.combine(
                cursor.date() + timedelta(days=1), datetime.min.time()
            )
            self._insert_segment(cursor, next_midnight, subject)
            cursor = next_midnight
        self._insert_segment(cursor, end, subject)

    def _insert_segment(self, start: datetime, end: datetime, subject: str) -> None:
        self.conn.execute(
            "INSERT INTO intervals (started_at, ended_at, seconds, subject) "
            "VALUES (?, ?, ?, ?)",
            (_fmt(start), _fmt(end), (end - start).total_seconds(), subject),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # Lecture
    # ------------------------------------------------------------------ #
    def seconds_for_day(self, day: date, subject: str | None = None) -> float:
        """Total du jour : global si subject est None, sinon pour cette matière."""
        clause, params = _subject_filter(subject)
        row = self.conn.execute(
            "SELECT COALESCE(SUM(seconds), 0) FROM intervals "
            "WHERE substr(started_at, 1, 10) = ?" + clause,
            (day.isoformat(), *params),
        ).fetchone()
        return row[0]

    def daily_seconds(
        self, first_day: date, last_day: date, subject: str | None = None
    ) -> list[tuple[date, float]]:
        """Secondes étudiées par jour sur une plage inclusive (jours vides = 0).
        Global si subject est None, sinon limité à cette matière."""
        clause, params = _subject_filter(subject)
        rows = self.conn.execute(
            "SELECT substr(started_at, 1, 10) AS jour, SUM(seconds) "
            "FROM intervals WHERE substr(started_at, 1, 10) BETWEEN ? AND ?"
            + clause + " GROUP BY jour",
            (first_day.isoformat(), last_day.isoformat(), *params),
        ).fetchall()
        counts = {date.fromisoformat(j): s for j, s in rows}
        result = []
        day = first_day
        while day <= last_day:
            result.append((day, counts.get(day, 0.0)))
            day += timedelta(days=1)
        return result

    def seconds_by_subject(self, first_day: date, last_day: date) -> dict[str, float]:
        """Secondes étudiées par matière sur une plage inclusive."""
        rows = self.conn.execute(
            "SELECT subject, SUM(seconds) FROM intervals "
            "WHERE substr(started_at, 1, 10) BETWEEN ? AND ? "
            "AND subject != '' "
            "GROUP BY subject COLLATE NOCASE ORDER BY SUM(seconds) DESC",
            (first_day.isoformat(), last_day.isoformat()),
        ).fetchall()
        return {subject: seconds for subject, seconds in rows}

    def subjects(self) -> list[str]:
        """Matières déjà tapées au moins une fois (ordre alphabétique)."""
        rows = self.conn.execute(
            "SELECT subject FROM intervals WHERE subject != '' "
            "GROUP BY subject COLLATE NOCASE ORDER BY subject COLLATE NOCASE"
        ).fetchall()
        return [r[0] for r in rows]

    def clear_today_and_subjects(self, today: date) -> int:
        """Efface tout aujourd'hui + tous les enregistrements avec matière.
        Renvoie le nombre d'enregistrements supprimés."""
        cursor = self.conn.execute(
            "DELETE FROM intervals WHERE substr(started_at, 1, 10) = ? OR subject != ''",
            (today.isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    def days_with_study(self) -> set[date]:
        rows = self.conn.execute(
            "SELECT DISTINCT substr(started_at, 1, 10) FROM intervals "
            "WHERE seconds > 0"
        ).fetchall()
        return {date.fromisoformat(r[0]) for r in rows}

    def current_streak(self, today: date | None = None) -> int:
        """Nombre de jours consécutifs d'étude jusqu'à aujourd'hui.

        Si aujourd'hui n'est pas encore compté, la série est prolongée
        depuis hier (la journée en cours ne casse pas la série).
        """
        today = today or date.today()
        days = self.days_with_study()
        if not days:
            return 0
        cursor = today if today in days else today - timedelta(days=1)
        if cursor not in days:
            return 0
        streak = 0
        while cursor in days:
            streak += 1
            cursor -= timedelta(days=1)
        return streak
