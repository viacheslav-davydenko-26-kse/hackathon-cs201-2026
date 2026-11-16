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


def facts_from_rows(catalog: dict[str, dict], by_metric: dict[str, list[dict]]) -> list[dict]:
    """catalog: metric_id → {title_uk, unit, kind, category}; by_metric: metric_id → рядки region_metrics."""
    facts: list[dict] = []

    for metric_id, rows in by_metric.items():
        meta = catalog.get(metric_id)
        if not meta:
            continue
        title = meta["title_uk"]
        unit = meta["unit"]
        kind = meta["kind"]
        category = meta["category"]

        # 1. Категоріальні метрики (nmt_top_elective, cars_top_brand тощо)
        if kind == "categorical":
            by_text = defaultdict(list)
            for r in rows:
                if r["value_text"]:
                    by_text[r["value_text"]].append(r["region_id"])

            for r in rows:
                val_txt = r["value_text"]
                if not val_txt:
                    continue
                cons = sorted(by_text[val_txt])
                facts.append({
                    "region_id": r["region_id"],
                    "metric_id": metric_id,
                    "category": category,
                    "kind": "categorical",
                    "text_uk": f"{title} — {val_txt}",
                    "consistent": json.dumps(cons, ensure_ascii=False),
                    "info": calc_info(cons),
                    "riddle_uk": None,
                })

        # 2. Числові метрики (rank, relative, raw)
        elif kind == "numeric":
            valid = [r for r in rows if r["value"] is not None]
            if not valid:
                continue

            avg_val = sum(r["value"] for r in valid) / len(valid)
            top3 = sorted([r["region_id"] for r in valid if r["rank"] and r["rank"] <= 3])
            bot3 = sorted([r["region_id"] for r in valid if r["rank"] and r["n_ranked"] and r["rank"] > r["n_ranked"] - 3])

            buckets = defaultdict(list)
            reg_bucket = {}
            for r in valid:
                diff_pct = ((r["value"] - avg_val) / avg_val) * 100.0 if avg_val != 0 else 0.0
                b = int(round(diff_pct / 10.0) * 10)
                buckets[b].append(r["region_id"])
                reg_bucket[r["region_id"]] = b

            for r in valid:
                reg = r["region_id"]
                val = r["value"]
                rank = r["rank"]
                n_ranked = r["n_ranked"]

                # A. Rank
                rank1_regions = sorted([r["region_id"] for r in valid if r["rank"] == 1])

                # Усередині циклу по регіонах:
                if rank == 1:
                    if len(rank1_regions) == 1:
                        r1_text = f"1-ше місце в Україні: {title}"
                    else:
                        r1_text = f"Ділить 1-ше місце в Україні: {title}"
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": r1_text,
                        "consistent": json.dumps(rank1_regions), "info": calc_info(rank1_regions), "riddle_uk": None,
                    })
                elif rank and rank <= 3:
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": f"У топ-3 областей за показником «{title}»",
                        "consistent": json.dumps(top3), "info": calc_info(top3), "riddle_uk": None,
                    })
                elif rank and n_ranked and rank > n_ranked - 3:
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": f"В останніх 3 областях за показником «{title}»",
                        "consistent": json.dumps(bot3), "info": calc_info(bot3), "riddle_uk": None,
                    })

                # B. Relative (бакети ±10%)
                b = reg_bucket[reg]
                cons_rel = sorted(buckets[b])
                if b == 0:
                    rel_txt = f"{title}: приблизно на рівні середнього по Україні (±10%)"
                elif b > 0:
                    rel_txt = f"{title}: приблизно на {abs(b)}% вище за середнє по Україні"
                else:
                    rel_txt = f"{title}: приблизно на {abs(b)}% нижче за середнє по Україні"

                facts.append({
                    "region_id": reg, "metric_id": metric_id, "category": category,
                    "kind": "relative", "text_uk": rel_txt,
                    "consistent": json.dumps(cons_rel), "info": calc_info(cons_rel), "riddle_uk": None,
                })

                # C. Raw (точне значення)
                cons_raw = [reg]
                val_str = f"{val:g}" if isinstance(val, int) or val.is_integer() else f"{val:.2f}"
                facts.append({
                    "region_id": reg, "metric_id": metric_id, "category": category,
                    "kind": "raw", "text_uk": f"{title}: {val_str} {unit}".strip(),
                    "consistent": json.dumps(cons_raw), "info": calc_info(cons_raw), "riddle_uk": None,
                })

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
      * види: rank (топ-1/топ-3/останні-3), relative (бакети ±10%), raw, categorical;
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
