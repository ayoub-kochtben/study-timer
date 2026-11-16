import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


def make_db(tmp_path):
    return Database(str(tmp_path / "test.db"))


def test_empty_database_returns_zero(db_in_tmp):
    db = db_in_tmp
    assert db.seconds_for_day(date(2026, 11, 16)) == 0.0
    assert db.current_streak(today=date(2026, 11, 16)) == 0
    assert db.daily_seconds(date(2026, 11, 10), date(2026, 11, 16)) == [
        (date(2026, 11, d), 0.0) for d in range(10, 17)
    ]


def test_insert_and_sum_single_day(tmp_path):
    db = make_db(tmp_path)
    db.insert_interval(
        datetime(2026, 11, 16, 10, 0, 0), datetime(2026, 11, 16, 10, 25, 30)
    )
    assert db.seconds_for_day(date(2026, 11, 16)) == 25.5 * 60


def test_interval_across_midnight_is_split(tmp_path):
    db = make_db(tmp_path)
    db.insert_interval(
        datetime(2026, 11, 15, 23, 0, 0), datetime(2026, 11, 16, 1, 0, 0)
    )
    assert db.seconds_for_day(date(2026, 11, 15)) == 3600.0
    assert db.seconds_for_day(date(2026, 11, 16)) == 3600.0


def test_zero_or_inverted_interval_is_ignored(tmp_path):
    db = make_db(tmp_path)
    db.insert_interval(datetime(2026, 11, 16, 10, 0), datetime(2026, 11, 16, 10, 0))
    db.insert_interval(datetime(2026, 11, 16, 10, 5), datetime(2026, 11, 16, 10, 0))
    assert db.seconds_for_day(date(2026, 11, 16)) == 0.0


def test_daily_seconds_fills_empty_days_with_zero(tmp_path):
    db = make_db(tmp_path)
    db.insert_interval(
        datetime(2026, 11, 12, 8, 0, 0), datetime(2026, 11, 12, 9, 0, 0)
    )
    db.insert_interval(
        datetime(2026, 11, 16, 8, 0, 0), datetime(2026, 11, 16, 8, 30, 0)
    )
    result = db.daily_seconds(date(2026, 11, 11), date(2026, 11, 16))
    assert dict(result)[date(2026, 11, 11)] == 0.0
    assert dict(result)[date(2026, 11, 12)] == 3600.0
    assert dict(result)[date(2026, 11, 15)] == 0.0
    assert dict(result)[date(2026, 11, 16)] == 1800.0


def test_streak_counts_consecutive_days_ending_today(tmp_path):
    db = make_db(tmp_path)
    today = date(2026, 11, 16)
    for offset in (0, 1, 2):  # aujourd'hui, hier, avant-hier
        day = today - timedelta(days=offset)
        db.insert_interval(
            datetime(day.year, day.month, day.day, 9, 0, 0),
            datetime(day.year, day.month, day.day, 10, 0, 0),
        )
    assert db.current_streak(today=today) == 3


def test_streak_continues_from_yesterday_when_today_empty(tmp_path):
    db = make_db(tmp_path)
    today = date(2026, 11, 16)
    for offset in (1, 2):  # hier et avant-hier, rien aujourd'hui
        day = today - timedelta(days=offset)
        db.insert_interval(
            datetime(day.year, day.month, day.day, 9, 0, 0),
            datetime(day.year, day.month, day.day, 10, 0, 0),
        )
    assert db.current_streak(today=today) == 2


def test_streak_broken_by_missing_day(tmp_path):
    db = make_db(tmp_path)
    today = date(2026, 11, 16)
    for offset in (0, 2):  # aujourd'hui, mais trou hier
        day = today - timedelta(days=offset)
        db.insert_interval(
            datetime(day.year, day.month, day.day, 9, 0, 0),
            datetime(day.year, day.month, day.day, 10, 0, 0),
        )
    assert db.current_streak(today=today) == 1
