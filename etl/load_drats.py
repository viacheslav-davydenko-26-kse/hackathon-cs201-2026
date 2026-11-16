"""Держстат: data/drats/sssu_{birth,mortality,marriage_divorce}.json.gz (SDMX). Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv): births, births_per_1000, deaths, deaths_per_1000, deaths_per_birth, marriages(_per_1000), divorces(_per_1000), divorces_per_100_marriages, mother_age_avg + series
"""
from __future__ import annotations

from app.domain import EtlTables
from etl.base import EtlContext, Step


class DratsStep(Step):
    name = "drats"

    def run(self, ctx: EtlContext) -> EtlTables:
        raise NotImplementedError("DratsStep.run — Ілля")
