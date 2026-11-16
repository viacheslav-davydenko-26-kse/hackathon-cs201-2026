"""Населення (01.01.2022) і площі → regions. Власник: Вадім.

Поки не реалізовано, run_all бере population/area_km2 з data/parsed/regions.csv.
"""
from __future__ import annotations

from etl.base import EtlContext


def load_population(ctx: EtlContext) -> dict[str, tuple[int | None, float | None]]:
    """region_id → (population, area_km2) для всіх 27 регіонів. Джерело: data/population/*.json.gz."""
    raise NotImplementedError("load_population — Вадім")
