"""Звіт якості даних: `python -m etl.check`. Власник: Ілля.

Кожна перевірка — `Check`; додавай нові в CHECKS. Виходить з кодом 1, якщо є error-результати.
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from app.repository import Repository

MIN_FACTS = 8
MIN_METRICS = 8


@dataclass
class CheckResult:
    name: str
    level: Literal["ok", "warn", "error"]
    details: list[str] = field(default_factory=list)


class Check(ABC):
    name = "check"

    @abstractmethod
    def run(self, repo: Repository) -> CheckResult: ...


class MetricsCoverage(Check):
    name = "≥ 8 метрик на ігровий регіон"

    def run(self, repo):
        bad = [f"{r.id}: {n}" for r in repo.playable_regions()
               if (n := len(repo.region_metrics(r.id))) < MIN_METRICS]
        return CheckResult(self.name, "error" if bad else "ok", bad)


class FactsCoverage(Check):
    name = "≥ 8 фактів на ігровий регіон"

    def run(self, repo):
        if not repo.facts():
            return CheckResult(self.name, "warn", ["facts порожня — build_facts ще не реалізовано"])
        bad = [f"{r.id}: {n}" for r in repo.playable_regions() if (n := len(repo.facts(r.id))) < MIN_FACTS]
        return CheckResult(self.name, "error" if bad else "ok", bad)


class NanMatrix(Check):
    """Регіон × метрика, де значення нема; виводить зведення пропусків."""
    name = "NaN-матриця"

    def run(self, repo: Repository) -> CheckResult:
        metrics = [m.id for m in repo.metrics()]
        details: list[str] = []
        for reg in repo.playable_regions():
            present = {
                rm.metric_id
                for rm in repo.region_metrics(reg.id)
                if rm.value is not None or rm.value_text
            }
            missing = [m for m in metrics if m not in present]
            if missing:
                details.append(f"{reg.id} ({len(missing)}/{len(metrics)}): {', '.join(missing)}")
        return CheckResult(self.name, "warn" if details else "ok", details)


class SourceUrls(Check):
    """У кожної метрики заповнені source_name та source_url."""
    name = "source_url у metrics"

    def run(self, repo: Repository) -> CheckResult:
        bad = [m.id for m in repo.metrics() if not m.source_name or not m.source_url]
        return CheckResult(self.name, "error" if bad else "ok", bad)


CHECKS: list[Check] = [MetricsCoverage(), FactsCoverage(), NanMatrix(), SourceUrls()]


def main(repo: Repository | None = None) -> int:
    from app.config import DB_PATH, PARSED_DIR
    from app.repository import CsvRepository, SqliteRepository
    repo = repo or (SqliteRepository(DB_PATH) if DB_PATH.exists() else CsvRepository(PARSED_DIR))
    failed = False
    for c in CHECKS:
        try:
            res = c.run(repo)
        except NotImplementedError:
            res = CheckResult(c.name, "warn", ["not implemented"])
        failed |= res.level == "error"
        print(f"[{res.level.upper():5}] {res.name}")
        for d in res.details:
            print(f"        {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
