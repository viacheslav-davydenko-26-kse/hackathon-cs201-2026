"""Бали, «гаряче/холодно», відстані. Власник: Слава."""
from math import asin, cos, radians, sin, sqrt

HINT_MULT = [1.0, 0.8, 0.6, 0.45, 0.3]
SPEED_BONUS_MAX = 100
SOLO_ATTEMPT_MULT = 0.5


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Відстань у км між двома точками."""
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def heat(distance_km: float) -> str:
    if distance_km < 150:
        return "hot"
    if distance_km < 300:
        return "warm"
    if distance_km < 500:
        return "cool"
    return "cold"


def points(correct: bool, distance_km: float, hint_index: int, attempt: int = 1) -> int:
    """hint_index — індекс останньої відкритої підказки; attempt — 1-based (соло)."""
    mult = HINT_MULT[min(hint_index, len(HINT_MULT) - 1)]
    base = 1000 * mult if correct else 500 * mult * max(0.0, 1 - distance_km / 500)
    return round(base * SOLO_ATTEMPT_MULT ** (attempt - 1))


def speed_bonus(seconds_left: float, round_seconds: float) -> int:
    if round_seconds <= 0:
        return 0
    return round(SPEED_BONUS_MAX * max(0.0, min(1.0, seconds_left / round_seconds)))
