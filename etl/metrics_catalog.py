"""Каталог метрик для тексту підказок. Власник: Матвій.

Базові поля (title, unit, category, source, higher_is) лежать у data/parsed/metrics.csv і йдуть у картку.
Тут лише те, що потрібно підказкам: коротка назва (`label`) і коротка одиниця (`unit`), щоб
підказка вміщалась в один рядок на телефоні. Метрика без запису бере title_uk/unit із metrics.csv.

Підказка НЕ містить назви регіону: це опис «тут …».
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    label: str | None = None          # коротка назва для підказки; None → title_uk
    unit: str | None = None           # коротка одиниця для raw; None → unit з metrics.csv, "" → без одиниці
    enabled: bool = True              # False → метрика не стає підказкою (але є в картці)
    period_from_unit: bool = False    # raw-підказка додає період з unit («… за період 1 січня – 20 серпня 2025»)


_SPECS = [
    # war — ранги/відхилення рахуються в спільному вікні; raw-підказка називає це вікно
    MetricSpec("alerts_count", "Повітряних тривог", "", period_from_unit=True),
    MetricSpec("alerts_hours", "Годин під тривогою", "", period_from_unit=True),
    MetricSpec("alerts_longest_hours", "Найдовша тривога", "год"),
    MetricSpec("alerts_night_share", "Нічні тривоги (00–06)", "%"),
    MetricSpec("alerts_avg_minutes", "Середня тривога", "хв"),
    # demography
    MetricSpec("population", "Населення", "осіб"),
    MetricSpec("age_avg", "Середній вік", "років"),
    MetricSpec("births", "Народжень за рік", ""),
    MetricSpec("births_per_1000", "Народжуваність", "на 1000 осіб"),
    MetricSpec("mother_age_avg", "Вік матері при пологах", "років"),
    MetricSpec("deaths", "Смертей за рік", ""),
    MetricSpec("deaths_per_1000", "Смертність", "на 1000 осіб"),
    MetricSpec("deaths_per_birth", "Смертей на одне народження", ""),
    MetricSpec("marriages", "Шлюбів за рік", ""),
    MetricSpec("divorces", "Розлучень за рік", ""),
    MetricSpec("marriages_per_1000", "Шлюбність", "на 1000 осіб"),
    MetricSpec("divorces_per_1000", "Розлучуваність", "на 1000 осіб"),
    MetricSpec("divorces_per_100_marriages", "Розлучень на 100 шлюбів", ""),
    # education
    MetricSpec("nmt_participants", "Учасників НМТ", ""),
    MetricSpec("nmt_participants_per_1000", "Учасників НМТ на 1000 жителів", ""),
    MetricSpec("nmt_avg_ukr", "Середній бал НМТ з української", ""),
    MetricSpec("nmt_avg_math", "Середній бал НМТ з математики", ""),
    MetricSpec("nmt_avg_hist", "Середній бал НМТ з історії", ""),
    MetricSpec("nmt_180_ukr", "Частка 180+ з української", "%"),
    MetricSpec("nmt_180_math", "Частка 180+ з математики", "%"),
    MetricSpec("nmt_180_hist", "Частка 180+ з історії", "%"),
    MetricSpec("nmt_any_180_share", "Частка 180+ хоч з одного предмета", "%"),
    MetricSpec("nmt_eng_share", "Обрали англійську на НМТ", "%"),
    MetricSpec("nmt_top_elective", "Топ-предмет НМТ на вибір", None),
    MetricSpec("nmt_top_elective_non_eng", "Топ-предмет НМТ на вибір, крім англійської", None),
]

#: metric_id → MetricSpec.
CATALOG: dict[str, MetricSpec] = {s.metric_id: s for s in _SPECS}


def spec(metric_id: str) -> MetricSpec:
    return CATALOG.get(metric_id) or MetricSpec(metric_id)


def label(metric_id: str, title_uk: str) -> str:
    return spec(metric_id).label or title_uk


def hint_unit(metric_id: str, unit: str | None) -> str:
    short = spec(metric_id).unit
    return (unit or "") if short is None else short


def period(unit: str | None) -> str:
    """«тривог за період 1 січня – 20 серпня 2025» → «1 січня – 20 серпня 2025»; без періоду → ""."""
    _, sep, rest = (unit or "").partition("за період ")
    return rest.strip() if sep else ""
