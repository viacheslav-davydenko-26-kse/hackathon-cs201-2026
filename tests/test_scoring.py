"""Бали, heat і таймінг кімнат. Власник: Слава."""
import pytest

from app.game.rooms import next_hint_at, open_hint_count
from app.game.scoring import haversine, heat, points, speed_bonus


def test_haversine_lviv_kyiv():
    assert haversine(49.84, 24.03, 50.45, 30.52) == pytest.approx(467, abs=5)


@pytest.mark.parametrize("d,h", [(0, "hot"), (149, "hot"), (150, "warm"), (299, "warm"), (499, "cool"), (500, "cold")])
def test_heat(d, h):
    assert heat(d) == h


def test_points():
    assert points(True, 0, 0) == 1000
    assert points(True, 0, 4) == 300
    assert points(True, 0, 0, attempt=2) == 500
    assert points(False, 250, 0) == 250
    assert points(False, 600, 0) == 0


def test_speed_bonus():
    assert speed_bonus(35, 35) == 100
    assert speed_bonus(0, 35) == 0
    assert speed_bonus(-5, 35) == 0


@pytest.mark.parametrize("dt,opened,nxt", [(-1, 0, 0), (0, 1, 7), (6.9, 1, 7), (7, 2, 14), (28, 5, None), (99, 5, None)])
def test_hint_timing(dt, opened, nxt):
    assert open_hint_count(100, 100 + dt, 35) == opened
    if dt >= 0:
        assert next_hint_at(100, 100 + dt, 35) == (None if nxt is None else 100 + nxt)
