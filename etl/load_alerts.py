"""Повітряні тривоги: data/alerts/official_data_uk.csv, лише level == 'oblast'. Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv): alerts_count, alerts_hours, alerts_longest_hours, alerts_night_share, alerts_avg_minutes + series (помісячно)
"""
from __future__ import annotations

from app.domain import EtlTables
from etl.base import EtlContext, Step


class AlertsStep(Step):
    name = "alerts"

    def run(self, ctx: EtlContext) -> EtlTables:
        raise NotImplementedError("AlertsStep.run — Ілля")
