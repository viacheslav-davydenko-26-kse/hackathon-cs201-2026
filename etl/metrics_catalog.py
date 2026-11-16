"""Каталог метрик + шаблони тексту фактів. Власник: Матвій.

Базові поля (title, unit, category, source, higher_is) вже є в data/parsed/metrics.csv —
тут лише те, чого там нема: шаблони речень для build_facts.

Плейсхолдери шаблонів (str.format):
  {title}  назва метрики з малої      {unit}  одиниця         {value}  значення (форматоване)
  {rank}   місце                       {n}     з-поміж скількох {pct}   відхилення від середнього, % (без знака)
  {dir}    'вище' | 'нижче'            {text}  value_text (categorical)
Шаблони НЕ містять назви регіону: це підказка «Тут …».
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import FactKind


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    templates: dict[FactKind, str] = field(default_factory=dict)
    enabled: bool = True              # False → метрика не стає підказкою (але є в картці)
    value_format: str = "{:g}"


DEFAULT_TEMPLATES: dict[FactKind, str] = {
    "rank": "Тут {rank}-е місце з {n} за показником «{title}»",
    "relative": "Показник «{title}» тут на {pct}% {dir} за середній по Україні",
    "raw": "{title}: {value} {unit}",
    "categorical": "{title}: {text}",
}

#: metric_id → MetricSpec. Заповнює Матвій; метрики без запису використовують DEFAULT_TEMPLATES.
CATALOG: dict[str, MetricSpec] = {}


def spec(metric_id: str) -> MetricSpec:
    return CATALOG.get(metric_id) or MetricSpec(metric_id)


def template(metric_id: str, kind: FactKind) -> str:
    return spec(metric_id).templates.get(kind) or DEFAULT_TEMPLATES[kind]
