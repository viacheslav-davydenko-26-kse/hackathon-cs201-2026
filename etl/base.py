"""Каркас ETL: інтерфейс кроку, ранги, валідація, запис у SQLite. Контракт — змінює Слава/Ілля разом.

Кожне джерело — це `Step`, що повертає `EtlTables` (app/domain.py). Кроки незалежні:
їх можна писати паралельно, і run_all просто склеює результати.
"""
from __future__ import annotations

import json
import math
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.domain import EtlTables, Fact, MetricInfo, RegionInfo, RegionMetric

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class EtlContext:
    data_dir: Path = ROOT / "data"
    parsed_dir: Path = ROOT / "data" / "parsed"
    db_path: Path = ROOT / "db" / "game.sqlite"
    schema_path: Path = ROOT / "db" / "schema.sql"
    static_dir: Path = ROOT / "static"
    regions: dict[str, RegionInfo] = field(default_factory=dict)   # заповнює run_all

    @property
    def playable_ids(self) -> list[str]:
        return [r.id for r in self.regions.values() if r.playable]


class Step(ABC):
    """Один ETL-крок (одне джерело даних).

    Контракт `run()`:
      * читає лише з ctx.data_dir (сирі файли), нічого не пише;
      * region_id — тільки через etl.regions.normalize_region();
      * повертає `MetricInfo` для КОЖНОЇ метрики, яку віддає (id унікальні між кроками);
      * значення «на 1000» рахує через ctx.regions[id].population;
      * rank/n_ranked можна не заповнювати — run_all перерахує через compute_ranks();
      * регіон без даних — просто нема рядка (не 0 і не NaN).
    """

    name: str = "step"

    @abstractmethod
    def run(self, ctx: EtlContext) -> EtlTables: ...


def compute_ranks(rows: list[RegionMetric], metrics: dict[str, MetricInfo],
                  only: set[str] | None = None) -> list[RegionMetric]:
    """rank 1 = найбільше значення (незалежно від higher_is); рівні значення ділять ранг (1,2,2,4).
    Рахується лише серед регіонів з `only` (ігрових), якщо передано. Categorical → rank=None."""
    by_metric: dict[str, list[RegionMetric]] = {}
    for r in rows:
        by_metric.setdefault(r.metric_id, []).append(r)
    out: list[RegionMetric] = []
    for mid, group in by_metric.items():
        numeric = metrics.get(mid) is not None and metrics[mid].kind == "numeric"
        ranked = [r for r in group if numeric and _ok(r.value) and (only is None or r.region_id in only)]
        values = sorted((r.value for r in ranked), reverse=True)
        for r in group:
            if r in ranked:
                out.append(_replace(r, rank=values.index(r.value) + 1, n_ranked=len(values)))
            else:
                out.append(_replace(r, rank=None, n_ranked=None))
    return out


def validate(tables: EtlTables, region_ids: set[str]) -> list[str]:
    """Список проблем (порожній = ок). run_all падає, якщо список не порожній."""
    problems: list[str] = []
    metric_ids = [m.id for m in tables.metrics]
    dup = {m for m in metric_ids if metric_ids.count(m) > 1}
    if dup:
        problems.append(f"duplicate metric ids: {sorted(dup)}")
    known = set(metric_ids)
    seen: set[tuple[str, str]] = set()
    for r in tables.region_metrics:
        if r.region_id not in region_ids:
            problems.append(f"unknown region {r.region_id!r} in {r.metric_id}")
        if r.metric_id not in known:
            problems.append(f"region_metrics uses undeclared metric {r.metric_id!r}")
        if (r.region_id, r.metric_id) in seen:
            problems.append(f"duplicate value {r.region_id}/{r.metric_id}")
        seen.add((r.region_id, r.metric_id))
        if r.value is None and not r.value_text:
            problems.append(f"empty value {r.region_id}/{r.metric_id}")
    for s in tables.series:
        if s.metric_id not in known:
            problems.append(f"series uses undeclared metric {s.metric_id!r}")
    return problems[:50]


# ------------------------------------------------------------------ запис у SQLite
def write_db(path: Path, schema_path: Path, regions: list[RegionInfo], tables: EtlTables,
             facts: list[Fact]) -> None:
    """Пише в тимчасовий файл і атомарно підміняє — сервер ніколи не бачить напівзаписану БД."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        _insert(conn, "regions", [asdict(r) | {"playable": int(r.playable)} for r in regions])
        _insert(conn, "metrics", [asdict(m) for m in tables.metrics])
        _insert(conn, "region_metrics", [asdict(r) for r in tables.region_metrics])
        _insert(conn, "series", [asdict(s) for s in tables.series])
        _insert(conn, "facts", [{k: v for k, v in asdict(f).items() if k != "category"}
                                | {"consistent": json.dumps(sorted(f.consistent))} for f in facts])
        conn.commit()
    finally:
        conn.close()
    tmp.replace(path)


def _insert(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    conn.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [tuple(r[c] for c in cols) for r in rows])


def _ok(v: float | None) -> bool:
    return v is not None and not math.isnan(v)


def _replace(r: RegionMetric, **kw) -> RegionMetric:
    return RegionMetric(**(asdict(r) | kw))
