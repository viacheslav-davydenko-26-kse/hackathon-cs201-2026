"""Генерація фактів із region_metrics. Власник: Матвій (інтерфейс `FactGenerator` — контракт).

Вхід: регіони, метрики, region_metrics (з рангами). Вихід: list[Fact] (app/domain.py), який
run_all пише в таблицю facts, а app.game.hints.FactHintPicker з неї читає.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod

from app.domain import Fact, MetricInfo, RegionInfo, RegionMetric


class FactGenerator(ABC):
    """Контракт `generate()`:
      * факти лише для ігрових регіонів; `consistent` рахується серед ігрових і містить сам регіон;
      * `info = info_bits(len(consistent), n_playable)`;
      * види: rank (топ-1/топ-3/останні-3), relative (бакети ±10%), raw, categorical;
      * метрика з NaN/без рядка для регіону → фактів з неї для регіону нема;
      * тексти з etl.metrics_catalog.template(), без назви регіону;
      * детермінований (без випадковості).
    """

    @abstractmethod
    def generate(self, regions: list[RegionInfo], metrics: list[MetricInfo],
                 region_metrics: list[RegionMetric]) -> list[Fact]: ...


def info_bits(n_consistent: int, n_playable: int) -> float:
    """Скільки біт інформації дає факт: log2(N / |consistent|). 0 = нічого не каже."""
    return math.log2(n_playable / max(1, n_consistent))


class DefaultFactGenerator(FactGenerator):
    def generate(self, regions, metrics, region_metrics) -> list[Fact]:
        raise NotImplementedError("DefaultFactGenerator.generate — Матвій")
