"""Населення (01.01.2022) і площі → regions + метрики population, age_avg. Власник: Вадім.

Джерело: data/population/sssu_population_structure.json.gz (Держстат, SDMX DF_POPULATION_STRUCTURE).
  PNMI_01 — чисельність наявного населення на 1 січня; PNMI_09 — середній вік населення.
Формат SDMX той самий, що в ДРАЦС, тому парсер спільний: etl.load_drats._extract_sdmx.
Площ у цьому джерелі нема — area_km2 лишається з data/parsed/regions.csv.
"""
from __future__ import annotations

from app.domain import EtlTables, MetricInfo, RegionMetric
from etl.base import EtlContext, Step
from etl.load_drats import _extract_sdmx

POP_SOURCE = "Держстат: Чисельність та склад населення (SDMX DF_POPULATION_STRUCTURE)"
POP_URL = "https://data.gov.ua/dataset/7b2cffb7-28f9-488b-85c6-fe364a42adde"
POP_YEAR = 2022
POP_FILE = "sssu_population_structure.json.gz"
_CODES = {"PNMI_01": "population", "PNMI_09": "age_avg"}

POP_METRICS: list[MetricInfo] = [
    MetricInfo("population", "Чисельність наявного населення на 1 січня", "осіб", "numeric", "demography",
               POP_SOURCE, POP_URL, POP_YEAR, "neutral"),
    MetricInfo("age_avg", "Середній вік населення на 1 січня", "років", "numeric", "demography",
               POP_SOURCE, POP_URL, POP_YEAR, "neutral"),
]


def _values(ctx: EtlContext) -> dict[tuple[str, str], float]:
    koatuu_to_region = {r.koatuu2: r.id for r in ctx.regions.values() if r.koatuu2}
    values, _ = _extract_sdmx(ctx.data_dir / "population" / POP_FILE, koatuu_to_region, _CODES, {}, year=POP_YEAR)
    return values


def load_population(ctx: EtlContext) -> dict[str, tuple[int | None, float | None]]:
    """region_id → (population, area_km2). Регіони без даних у джерелі не повертаються."""
    return {rid: (int(v), ctx.regions[rid].area_km2)
            for (rid, mid), v in _values(ctx).items() if mid == "population"}


class PopulationStep(Step):
    """Метрики population і age_avg (для фактів і картки)."""

    name = "population"

    def run(self, ctx: EtlContext) -> EtlTables:
        return EtlTables(
            metrics=list(POP_METRICS),
            region_metrics=[RegionMetric(region_id=rid, metric_id=mid, value=v, year=POP_YEAR)
                            for (rid, mid), v in sorted(_values(ctx).items())],
        )
