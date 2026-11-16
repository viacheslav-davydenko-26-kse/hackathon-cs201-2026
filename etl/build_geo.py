"""GeoJSON областей → static/ua.geojson + центроїди. Власник: Вадім.

Контракт вихідного файлу (його читає static/js/map.js) — docs/contract.md → «Геодані»:
FeatureCollection з 27 features, у кожної properties = {region_id, name_uk, short_uk, playable}.
Поки не реалізовано, run_all копіює готовий data/parsed/ua.geojson.
"""
from __future__ import annotations

from pathlib import Path

from etl.base import EtlContext


def build_geo(ctx: EtlContext, src: Path | None = None, dst: Path | None = None) -> dict[str, tuple[float, float]]:
    """Пише dst (default: ctx.static_dir / 'ua.geojson'), повертає region_id → (lat, lon) центроїда."""
    raise NotImplementedError("build_geo — Вадім")
