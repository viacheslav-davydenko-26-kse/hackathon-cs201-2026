"""Доступ до даних. Ігрова логіка працює ЛИШЕ через `Repository`, без SQL напряму.

Реалізації:
  * SqliteRepository — db/game.sqlite (основна, збирається `python -m etl.run_all`)
  * CsvRepository    — data/parsed/*.csv (фолбек, поки БД нема; без facts)
  * InMemoryRepository — для тестів: передаєш списки dataclass-ів

Власник інтерфейсу: Слава. Нові методи — лише через нього.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterable
from functools import cached_property
from pathlib import Path

from app.domain import Fact, MetricInfo, RegionInfo, RegionMetric, SeriesPoint, uk_sort_key
from app.errors import DataUnavailable, RegionNotFound


class Repository(ABC):
    """Read-only доступ до регіонів, метрик, фактів. Повертає незмінні dataclass-и."""

    @abstractmethod
    def regions(self) -> list[RegionInfo]:
        """Усі 27 регіонів (і ігрові, і неігрові), відсортовані за name_uk."""

    @abstractmethod
    def metrics(self) -> list[MetricInfo]: ...

    @abstractmethod
    def region_metrics(self, region_id: str | None = None, metric_id: str | None = None) -> list[RegionMetric]:
        """Фільтри необов'язкові й комбінуються через AND."""

    @abstractmethod
    def series(self, region_id: str, metric_id: str | None = None) -> list[SeriesPoint]:
        """Точки за зростанням period."""

    @abstractmethod
    def facts(self, region_id: str | None = None) -> list[Fact]:
        """Порожній список, якщо факти ще не згенеровано."""

    # ---- похідні методи (не перевизначати без потреби)
    def region(self, region_id: str) -> RegionInfo:
        for r in self.regions():
            if r.id == region_id:
                return r
        raise RegionNotFound(f"unknown region {region_id!r}")

    def playable_regions(self) -> list[RegionInfo]:
        return [r for r in self.regions() if r.playable]

    def metric(self, metric_id: str) -> MetricInfo:
        for m in self.metrics():
            if m.id == metric_id:
                return m
        raise KeyError(metric_id)


class InMemoryRepository(Repository):
    def __init__(self, regions: Iterable[RegionInfo] = (), metrics: Iterable[MetricInfo] = (),
                 region_metrics: Iterable[RegionMetric] = (), series: Iterable[SeriesPoint] = (),
                 facts: Iterable[Fact] = ()):
        self._regions = sorted(regions, key=lambda r: uk_sort_key(r.name_uk))
        self._metrics = list(metrics)
        self._rm = list(region_metrics)
        self._series = sorted(series, key=lambda s: s.period)
        self._facts = list(facts)

    def regions(self) -> list[RegionInfo]:
        return list(self._regions)

    def metrics(self) -> list[MetricInfo]:
        return list(self._metrics)

    def region_metrics(self, region_id=None, metric_id=None) -> list[RegionMetric]:
        return [x for x in self._rm
                if (region_id is None or x.region_id == region_id)
                and (metric_id is None or x.metric_id == metric_id)]

    def series(self, region_id, metric_id=None) -> list[SeriesPoint]:
        return [s for s in self._series
                if s.region_id == region_id and (metric_id is None or s.metric_id == metric_id)]

    def facts(self, region_id=None) -> list[Fact]:
        return [f for f in self._facts if region_id is None or f.region_id == region_id]


# ------------------------------------------------------------------ parsing helpers
def _f(v) -> float | None:
    return None if v in (None, "") else float(v)


def _i(v) -> int | None:
    return None if v in (None, "") else int(float(v))


def _s(v) -> str | None:
    return None if v in (None, "") else str(v)


def region_from_row(r: dict) -> RegionInfo:
    return RegionInfo(id=r["id"], name_uk=r["name_uk"], short_uk=r["short_uk"], playable=bool(int(r["playable"])),
                      lat=_f(r.get("lat")), lon=_f(r.get("lon")), iso=_s(r.get("iso")),
                      koatuu2=_s(r.get("koatuu2")), name_en=_s(r.get("name_en")),
                      population=_i(r.get("population")), area_km2=_f(r.get("area_km2")))


def metric_from_row(r: dict) -> MetricInfo:
    return MetricInfo(id=r["id"], title_uk=r["title_uk"], unit=_s(r.get("unit")), kind=r["kind"],
                      category=r["category"], source_name=_s(r.get("source_name")),
                      source_url=_s(r.get("source_url")), year=_i(r.get("year")),
                      higher_is=r.get("higher_is") or "neutral")


def region_metric_from_row(r: dict) -> RegionMetric:
    return RegionMetric(region_id=r["region_id"], metric_id=r["metric_id"], value=_f(r.get("value")),
                        value_text=_s(r.get("value_text")), year=_i(r.get("year")),
                        rank=_i(r.get("rank")), n_ranked=_i(r.get("n_ranked")))


def series_from_row(r: dict) -> SeriesPoint:
    return SeriesPoint(region_id=r["region_id"], metric_id=r["metric_id"], period=str(r["period"]),
                       value=float(r["value"]))


def fact_from_row(r: dict) -> Fact:
    return Fact(id=_i(r.get("id")), region_id=r["region_id"], metric_id=r["metric_id"], kind=r["kind"],
                text_uk=r["text_uk"], consistent=frozenset(json.loads(r["consistent"])),
                info=float(r["info"]), category=r.get("category") or "demography",
                riddle_uk=_s(r.get("riddle_uk")))


class _Cached(Repository):
    """Завантажує все один раз (дані маленькі: ~1–3 тис. рядків)."""

    @cached_property
    def _data(self) -> InMemoryRepository:
        return InMemoryRepository(**self._load())

    def _load(self) -> dict:
        raise NotImplementedError

    def regions(self): return self._data.regions()
    def metrics(self): return self._data.metrics()
    def region_metrics(self, region_id=None, metric_id=None): return self._data.region_metrics(region_id, metric_id)
    def series(self, region_id, metric_id=None): return self._data.series(region_id, metric_id)
    def facts(self, region_id=None): return self._data.facts(region_id)


class SqliteRepository(_Cached):
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _load(self) -> dict:
        if not self.db_path.exists():
            raise DataUnavailable(f"{self.db_path} not found; run `python -m etl.run_all`")
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = lambda sql: [dict(r) for r in conn.execute(sql)]  # noqa: E731
            facts_sql = ("SELECT f.*, m.category FROM facts f LEFT JOIN metrics m ON m.id = f.metric_id")
            return dict(regions=map(region_from_row, rows("SELECT * FROM regions")),
                        metrics=map(metric_from_row, rows("SELECT * FROM metrics")),
                        region_metrics=map(region_metric_from_row, rows("SELECT * FROM region_metrics")),
                        series=map(series_from_row, rows("SELECT * FROM series")),
                        facts=map(fact_from_row, rows(facts_sql)))
        except sqlite3.Error as e:
            raise DataUnavailable(str(e)) from e
        finally:
            conn.close()


class CsvRepository(_Cached):
    """Читає data/parsed/{regions,metrics,region_metrics,series}.csv (+ facts.csv, якщо є)."""

    def __init__(self, parsed_dir: Path):
        self.dir = Path(parsed_dir)

    def _read(self, name: str) -> list[dict]:
        p = self.dir / name
        if not p.exists():
            return []
        with p.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def _load(self) -> dict:
        if not (self.dir / "regions.csv").exists():
            raise DataUnavailable(f"{self.dir}/regions.csv not found")
        return dict(regions=map(region_from_row, self._read("regions.csv")),
                    metrics=map(metric_from_row, self._read("metrics.csv")),
                    region_metrics=map(region_metric_from_row, self._read("region_metrics.csv")),
                    series=map(series_from_row, self._read("series.csv")),
                    facts=map(fact_from_row, self._read("facts.csv")))
