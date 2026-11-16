"""Тимчасове джерело: уже розпарсені data/parsed/{metrics,region_metrics,series}.csv.

Дозволяє зібрати game.sqlite, поки сирі лоадери (load_*.py) не готові. Власник: Ілля.
"""
from __future__ import annotations

from app.domain import EtlTables
from app.repository import CsvRepository
from etl.base import EtlContext, Step


class ParsedCsvStep(Step):
    name = "parsed"

    def run(self, ctx: EtlContext) -> EtlTables:
        repo = CsvRepository(ctx.parsed_dir)
        return EtlTables(metrics=repo.metrics(), region_metrics=repo.region_metrics(),
                         series=[p for r in repo.regions() for p in repo.series(r.id)])
