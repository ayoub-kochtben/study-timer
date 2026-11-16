import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detection import (
    _coverage_ratio,
    _expanded_box,
    _bounding_box,
    debug_draw,
    select_face,
)
import numpy as np


def face_detection(score: float, x: int, y: int, w: int, h: int):
    return SimpleNamespace(
        categories=[SimpleNamespace(score=score)],
        bounding_box=SimpleNamespace(origin_x=x, origin_y=y, width=w, height=h),
    )


WIDTH, HEIGHT = 640, 480

# Visage plausible : 10 % de la largeur, du haut de l'image.
GOOD = face_detection(0.9, 280, 100, 64, 64)


def select(**overrides):
    args = {
        "min_confidence": 0.6,
        "min_box_fraction": 0.04,
    }
    args.update(overrides)
    return select_face([GOOD], WIDTH, HEIGHT, args["min_confidence"], args["min_box_fraction"])


def test_valid_face_is_selected_with_pixel_box():
    assert select() == (280, 100, 280 + 64, 100 + 64)


def test_low_confidence_face_is_rejected():
    face = face_detection(0.42, 280, 100, 64, 64)
    result = select_face([face], WIDTH, HEIGHT, 0.6, 0.04)
    assert result is None


def test_tiny_face_sized_box_is_rejected():
    # 64px = 10 % de 640 ; un objet 25px (~4 %) trop petit est refusé.
    small = face_detection(0.95, 280, 100, 25, 25)
    assert select_face([small], WIDTH, HEIGHT, 0.6, 0.04) is None


def test_narrow_but_tall_box_is_rejected():
    thin = face_detection(0.95, 280, 100, 20, 200)  # 20px < 4 % de 640
    assert select_face([thin], WIDTH, HEIGHT, 0.6, 0.04) is None


def test_best_qualifying_face_wins():
    better = face_detection(0.75, 100, 100, 80, 80)
    worse = face_detection(0.65, 300, 200, 64, 64)
    box = select_face([worse, better], WIDTH, HEIGHT, 0.6, 0.04)
    assert box == (100, 100, 180, 180)


def test_no_detection_returns_none():
    assert select_face([], WIDTH, HEIGHT, 0.6, 0.04) is None


# --------------------------------------------------------------------- #
# Géométrie "en main"
# --------------------------------------------------------------------- #
def test_expanded_box_grows_by_margin_and_clips():
    box = (100, 100, 200, 200)  # 100x100
    expanded = _expanded_box(box, 0.15, 640, 480)
    assert expanded == (85.0, 85.0, 215.0, 215.0)
    clipped = _expanded_box((10, 10, 30, 30), 0.5, 640, 480)
    assert clipped == (0.0, 0.0, 40.0, 40.0)


def test_coverage_ratio_counts_points_inside():
    box = (0, 0, 100, 100)
    points = [(10, 10), (50, 50), (150, 50), (200, 200)]
    assert _coverage_ratio(points, box) == 0.5
    assert _coverage_ratio([], box) == 0.0


def test_bounding_box_of_hand_points():
    points = [(10.0, 20.0), (40.0, 15.0), (30.0, 80.0)]
    assert _bounding_box(points) == (10, 15, 40, 80)


# --------------------------------------------------------------------- #
# Mode debug
# --------------------------------------------------------------------- #
from datetime import datetime

from engine import Observation


def make_result(**overrides):
    base = dict(
        observation=Observation(face_found=True, forbidden_in_hand=False, timestamp=datetime(2026, 11, 17, 9, 0, 0)),
        face_found=True,
        face_score=0.9,
        face_box=(100, 100, 200, 200),
        phone_boxes=[(300, 100, 380, 180)],
        hand_boxes=[(280, 140, 400, 260)],
    )
    base.update(overrides)
    from detection import FrameResult

    return FrameResult(**base)


def test_debug_draw_draws_all_boxes():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    shown = debug_draw(frame, make_result())
    assert shown.sum() > 0  # des tracés sont présents
    assert frame.sum() == 0  # l'image d'origine n'est pas modifiée


def test_debug_draw_without_detections_is_noop():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    shown = debug_draw(frame, make_result(face_box=None, phone_boxes=[], hand_boxes=[]))
    assert shown.sum() == 0
