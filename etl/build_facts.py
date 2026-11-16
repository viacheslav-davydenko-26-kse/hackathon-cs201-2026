"""Генерація фактів із region_metrics. Власник: Матвій (інтерфейс `FactGenerator` — контракт).

Вхід: регіони, метрики, region_metrics (з рангами). Вихід: list[Fact] (app/domain.py), який
run_all пише в таблицю facts, а app.game.hints.FactHintPicker з неї читає.
Алгоритм — `facts_from_rows()` (dict-и); `DefaultFactGenerator` — адаптер до інтерфейсу.

    python -m etl.build_facts      # швидка перевірка на data/parsed/*.csv
"""
from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import asdict

from app.domain import Fact, MetricInfo, RegionInfo, RegionMetric
from etl import metrics_catalog

TOTAL_PLAYABLE = 25


def calc_info(consistent: list[str]) -> float:
    return round(math.log2(TOTAL_PLAYABLE / max(1, len(consistent))), 3)


def load_catalog(metrics_csv: str | Path) -> dict[str, dict]:
    catalog = {}
    with open(metrics_csv, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            catalog[row["id"]] = row
    return catalog


def load_region_metrics(rm_csv: str | Path) -> dict[str, list[dict]]:
    by_metric = defaultdict(list)
    with open(rm_csv, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["value"] = float(row["value"]) if row["value"] != "" else None
            row["year"] = int(float(row["year"])) if row["year"] != "" else None
            row["rank"] = int(float(row["rank"])) if row["rank"] != "" else None
            row["n_ranked"] = int(float(row["n_ranked"])) if row["n_ranked"] != "" else None
            by_metric[row["metric_id"]].append(row)
    return by_metric


def build_all_facts(metrics_csv: str | Path, rm_csv: str | Path) -> list[dict]:
    return facts_from_rows(load_catalog(metrics_csv), load_region_metrics(rm_csv))


def _format_raw_value(value: int | float) -> str:
    """Use the same displayed precision for clue text and compatibility groups.

    Цілі — усі цифри з розділювачем тисяч (нерозривний пробіл): 1509515 → «1 509 515».
    Дробові — 2 знаки після крапки. Наукового запису («1.50952e+06») не буває.
    """
    text = f"{int(value):,}" if isinstance(value, int) or value.is_integer() else f"{value:,.2f}"
    return text.replace(",", "\u00a0")


#: Смуги відхилення від середнього по областях: (нижня межа, верхня межа) у % і текст.
#: Межі напіввідкриті [lo, hi). Текст і `consistent` беруться з ОДНІЄЇ смуги, тож твердження
#: «на 5–20% вище середнього» істинне рівно для регіонів у `consistent` — ні більше, ні менше.
RELATIVE_BANDS: list[tuple[float, float, str]] = [
    (-math.inf, -50, "менше половини середнього"),
    (-50, -35, "на 35–50% нижче середнього"),
    (-35, -20, "на 20–35% нижче середнього"),
    (-20, -5, "на 5–20% нижче середнього"),
    (-5, 5, "в межах ±5% від середнього"),
    (5, 20, "на 5–20% вище середнього"),
    (20, 35, "на 20–35% вище середнього"),
    (35, 50, "на 35–50% вище середнього"),
    (50, 100, "в 1,5–2 рази вище середнього"),
    (100, 200, "у 2–3 рази вище середнього"),
    (200, math.inf, "більш ніж утричі вище середнього"),
]


def relative_band(value: float, avg: float) -> int:
    """Індекс смуги в RELATIVE_BANDS для відхилення value від avg."""
    diff_pct = (value - avg) / avg * 100.0 if avg else 0.0
    for i, (lo, hi, _) in enumerate(RELATIVE_BANDS):
        if lo <= diff_pct < hi:
            return i
    return len(RELATIVE_BANDS) - 1


def _with_unit(value: str, unit: str) -> str:
    if not unit:
        return value
    return f"{value}{unit}" if unit.startswith("%") else f"{value} {unit}"


def _fact(region_id: str, metric_id: str, category: str, kind: str, text: str, consistent) -> dict:
    cons = sorted(consistent)
    return {
        "region_id": region_id, "metric_id": metric_id, "category": category, "kind": kind,
        "text_uk": text, "consistent": json.dumps(cons, ensure_ascii=False),
        "info": calc_info(cons), "riddle_uk": None,
    }


def facts_from_rows(catalog: dict[str, dict], by_metric: dict[str, list[dict]]) -> list[dict]:
    """catalog: metric_id → {title_uk, unit, kind, category}; by_metric: metric_id → рядки region_metrics.

    Тексти короткі: «{label}: {що саме}». label/одиниця — з etl.metrics_catalog, інакше з catalog.
    Середнє — просте середнє по регіонах з даними (а не зважене по населенню).
    """
    facts: list[dict] = []

    for metric_id, rows in by_metric.items():
        meta = catalog.get(metric_id)
        if not meta or not metrics_catalog.spec(metric_id).enabled:
            continue
        label = metrics_catalog.label(metric_id, meta["title_uk"])
        unit = metrics_catalog.hint_unit(metric_id, meta["unit"])
        category = meta["category"]

        # 1. Категоріальні: «Топ-предмет НМТ на вибір: біологія»
        if meta["kind"] == "categorical":
            by_text = defaultdict(set)
            for r in rows:
                if r["value_text"]:
                    by_text[r["value_text"]].add(r["region_id"])
            for r in rows:
                if r["value_text"]:
                    facts.append(_fact(r["region_id"], metric_id, category, "categorical",
                                       f"{label}: {r['value_text']}", by_text[r["value_text"]]))
            continue

        # 2. Числові: rank, relative, raw
        if meta["kind"] != "numeric":
            continue
        valid = [r for r in rows if r["value"] is not None]
        if not valid:
            continue

        # Різні значення можуть дати однаковий текст після округлення — групуємо тим самим форматером.
        by_displayed_value = defaultdict(set)
        for r in valid:
            by_displayed_value[_format_raw_value(r["value"])].add(r["region_id"])

        avg_val = sum(r["value"] for r in valid) / len(valid)
        by_band = defaultdict(set)
        for r in valid:
            by_band[relative_band(r["value"], avg_val)].add(r["region_id"])

        rank1 = {r["region_id"] for r in valid if r["rank"] == 1}
        top3 = {r["region_id"] for r in valid if r["rank"] and r["rank"] <= 3}
        bot3 = {r["region_id"] for r in valid if r["rank"] and r["n_ranked"] and r["rank"] > r["n_ranked"] - 3}

        period = metrics_catalog.period(meta["unit"]) if metrics_catalog.spec(metric_id).period_from_unit else ""
        raw_label = f"{label} ({period})" if period else label

        for r in valid:
            reg, rank, n_ranked = r["region_id"], r["rank"], r["n_ranked"]

            # A. Rank: 1-ше місце / трійка найвищих / трійка найнижчих (1 = найбільше значення)
            if rank == 1:
                text = f"{label}: найвищий показник серед областей" if len(rank1) == 1 \
                    else f"{label}: ділить найвищий показник серед областей"
                facts.append(_fact(reg, metric_id, category, "rank", text, rank1))
            elif rank and rank <= 3:
                facts.append(_fact(reg, metric_id, category, "rank", f"{label}: у трійці найвищих", top3))
            elif rank and n_ranked and rank > n_ranked - 3:
                facts.append(_fact(reg, metric_id, category, "rank", f"{label}: у трійці найнижчих", bot3))

            # B. Relative: смуга відхилення від середнього
            band = relative_band(r["value"], avg_val)
            facts.append(_fact(reg, metric_id, category, "relative",
                               f"{label}: {RELATIVE_BANDS[band][2]}", by_band[band]))

            # C. Raw: усі регіони з однаковим показаним значенням
            val_str = _format_raw_value(r["value"])
            facts.append(_fact(reg, metric_id, category, "raw",
                               f"{raw_label}: {_with_unit(val_str, unit)}", by_displayed_value[val_str]))

    return facts


def save_facts_to_sqlite(db_path: str | Path, facts: list[dict]) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM facts")
    cur.executemany(
        """
        INSERT INTO facts (region_id, metric_id, kind, text_uk, consistent, info, riddle_uk)
        VALUES (:region_id, :metric_id, :kind, :text_uk, :consistent, :info, :riddle_uk)
        """,
        facts,
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ інтерфейс
class FactGenerator(ABC):
    """Контракт `generate()`:
      * факти лише для ігрових регіонів; `consistent` рахується серед ігрових і містить сам регіон;
      * `info = info_bits(len(consistent), n_playable)`;
      * види: rank (топ-1/топ-3/останні-3), relative (смуги RELATIVE_BANDS), raw, categorical;
      * `consistent` — РІВНО ті регіони, для яких текст факту істинний;
      * метрика з NaN/без рядка для регіону → фактів з неї для регіону нема;
      * тексти без назви регіону;
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
        playable = {r.id for r in regions if r.playable}
        catalog = {m.id: {"title_uk": m.title_uk, "unit": m.unit or "", "kind": m.kind, "category": m.category}
                   for m in metrics}
        by_metric: dict[str, list[dict]] = defaultdict(list)
        for rm in region_metrics:
            if rm.region_id in playable:
                by_metric[rm.metric_id].append(asdict(rm))
        return [Fact(region_id=f["region_id"], metric_id=f["metric_id"], kind=f["kind"], text_uk=f["text_uk"],
                     consistent=frozenset(json.loads(f["consistent"])), info=f["info"], category=f["category"],
                     riddle_uk=f["riddle_uk"])
                for f in facts_from_rows(catalog, by_metric)]


if __name__ == "__main__":
    all_facts = build_all_facts("data/parsed/metrics.csv", "data/parsed/region_metrics.csv")
    print(f"Згенеровано фактів: {len(all_facts)}")
