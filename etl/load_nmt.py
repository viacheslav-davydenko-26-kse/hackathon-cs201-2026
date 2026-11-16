"""НМТ: data/nmt/OpenDataNMT2025.7z. Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv): nmt_participants(_per_1000), nmt_avg_{ukr,math,hist}, nmt_180_{ukr,math,hist}, nmt_any_180_share, nmt_eng_share, nmt_top_elective(_non_eng) (categorical)
"""
from __future__ import annotations

from app.domain import EtlTables
from etl.base import EtlContext, Step


class NmtStep(Step):
    name = "nmt"

    def run(self, ctx: EtlContext) -> EtlTables:
        raise NotImplementedError("NmtStep.run — Ілля")
