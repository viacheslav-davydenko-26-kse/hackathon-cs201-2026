"""Спільні доменні типи для ETL і бекенду. Контракт — змінює лише Слава.

Це внутрішні (Python) типи. Те, що їде по HTTP, описано в app/schemas.py.
Усі dataclass-и незмінні (frozen), тож їх безпечно передавати між модулями.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Category = Literal["war", "demography", "cars", "education"]
MetricKind = Literal["numeric", "categorical"]
HigherIs = Literal["better", "worse", "neutral"]
FactKind = Literal["rank", "relative", "raw", "categorical"]

CATEGORIES: tuple[Category, ...] = ("war", "demography", "cars", "education")

_UK_ALPHABET = {c: i for i, c in enumerate("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")}


def uk_sort_key(text: str) -> tuple[int, ...]:
    """Ключ сортування за українським алфавітом (str.sort ставить «І» перед «А»)."""
    return tuple(_UK_ALPHABET.get(c, 100 + ord(c)) for c in text.lower())


#: Джерело поточного часу (unix-секунди). У тестах підміняється фейковим годинником.
Clock = Callable[[], float]


@dataclass(frozen=True)
class RegionInfo:
    id: str                      # slug: 'lviv', 'kyiv_city'
    name_uk: str                 # 'Львівська область'
    short_uk: str                # 'Львівщина'
    playable: bool               # False для Криму, Севастополя (і, можливо, Луганської)
    lat: float | None = None     # центроїд
    lon: float | None = None
    iso: str | None = None       # 'UA-46'
    koatuu2: str | None = None   # '46'
    name_en: str | None = None   # назва з GeoJSON
    population: int | None = None
    area_km2: float | None = None


@dataclass(frozen=True)
class MetricInfo:
    id: str                      # 'alerts_hours'
    title_uk: str
    unit: str | None
    kind: MetricKind
    category: Category
    source_name: str | None = None
    source_url: str | None = None
    year: int | None = None
    higher_is: HigherIs = "neutral"


@dataclass(frozen=True)
class RegionMetric:
    region_id: str
    metric_id: str
    value: float | None = None       # numeric
    value_text: str | None = None    # categorical ('англійська мова')
    year: int | None = None
    rank: int | None = None          # 1 = найбільше значення; None для categorical / NaN
    n_ranked: int | None = None      # серед скількох регіонів з даними


@dataclass(frozen=True)
class SeriesPoint:
    region_id: str
    metric_id: str
    period: str                      # 'YYYY-MM' або 'YYYY'
    value: float


@dataclass(frozen=True)
class Fact:
    region_id: str
    metric_id: str
    kind: FactKind
    text_uk: str                     # готове речення БЕЗ назви регіону: 'Тут найпопулярніший предмет — історія'
    consistent: frozenset[str]       # регіони, для яких твердження теж істинне (містить region_id)
    info: float                      # log2(N_playable / len(consistent)); більше = сильніше видає відповідь
    category: Category = "demography"
    id: int | None = None
    riddle_uk: str | None = None     # Stretch: LLM-перефразування


@dataclass
class EtlTables:
    """Те, що віддає будь-який ETL-крок. Порожні списки — нормально."""
    metrics: list[MetricInfo] = field(default_factory=list)
    region_metrics: list[RegionMetric] = field(default_factory=list)
    series: list[SeriesPoint] = field(default_factory=list)

    def extend(self, other: EtlTables) -> None:
        self.metrics += other.metrics
        self.region_metrics += other.region_metrics
        self.series += other.series
