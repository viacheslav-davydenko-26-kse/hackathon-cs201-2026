"""Реєстрації ТЗ МВС через DuckDB (read_csv_auto, лише потрібні колонки). Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv): cars_per_1000, cars_ev_share, cars_age_avg, cars_top_brand (categorical), cars_top_color (categorical)
"""
from __future__ import annotations

from app.domain import EtlTables
from etl.base import EtlContext, Step


class CarsStep(Step):
    name = "cars"

    def run(self, ctx: EtlContext) -> EtlTables:
        raise NotImplementedError("CarsStep.run — Ілля")
