"""Тривоги (level == 'oblast') -> region_metrics + series + coverage.

Власник: Ілля.

Два входи до одних і тих самих функцій:
  * `python -m etl.load_alerts` — перезаписує data/parsed/*.csv (alerts_*-рядки);
  * `AlertsStep` — крок для `python -m etl.run_all --source raw` (нічого не пише, повертає EtlTables).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.domain import EtlTables
from app.repository import metric_from_row, region_metric_from_row, series_from_row
from etl.base import EtlContext, Step

KYIV_TZ = ZoneInfo("Europe/Kyiv")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
ALERTS_CSV = DATA_DIR / "alerts" / "official_data_uk.csv"
PARSED_DIR = DATA_DIR / "parsed"
PARTS_DIR = PARSED_DIR / "parts"

ALERTS_METRIC_IDS = (
    "alerts_count",
    "alerts_hours",
    "alerts_longest_hours",
    "alerts_night_share",
    "alerts_avg_minutes",
    "alerts_per_month",
    "alerts_hours_per_month",
)


def load_region_map(regions_csv: Path) -> dict[str, str]:
    """Повертає відображення name_uk -> region_id з regions.csv."""
    with regions_csv.open(encoding="utf-8", newline="") as f:
        return {row["name_uk"]: row["id"] for row in csv.DictReader(f)}


def parse_deduplicated_alerts(
    alerts_csv: Path,
    region_map: dict[str, str],
    year: int = 2025,
) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Читає official_data_uk.csv (level == 'oblast'), переводить у Europe/Kyiv та дедуплікує."""
    seen: set[tuple[str, str, str]] = set()
    by_region: dict[str, list[dict]] = defaultdict(list)
    raw_year_rows = 0
    dedup_year_rows = 0

    with alerts_csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["level"] != "oblast":
                continue

            oblast = row["oblast"]
            region_id = region_map.get(oblast)
            if not region_id:
                continue

            started_raw = row["started_at"]
            finished_raw = row["finished_at"]
            if not started_raw or not finished_raw:
                continue

            started_kyiv = datetime.fromisoformat(started_raw).astimezone(KYIV_TZ)
            if started_kyiv.year != year:
                continue

            raw_year_rows += 1
            dedup_key = (oblast, started_raw, finished_raw)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            finished_kyiv = datetime.fromisoformat(finished_raw).astimezone(KYIV_TZ)
            duration_hours = (finished_kyiv.timestamp() - started_kyiv.timestamp()) / 3600.0
            if duration_hours < 0:
                continue

            dedup_year_rows += 1
            by_region[region_id].append(
                {
                    "started": started_kyiv,
                    "finished": finished_kyiv,
                    "duration_hours": duration_hours,
                }
            )

    stats = {"raw_year_rows": raw_year_rows, "dedup_year_rows": dedup_year_rows}
    return by_region, stats


def compute_alerts_data(
    alerts_by_region: dict[str, list[dict]],
    year: int = 2025,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Обчислює агреговані метрики, помісячні серії та метадані покриття."""
    metrics_rows: list[dict] = []
    series_rows: list[dict] = []
    coverage_meta: dict[str, dict] = {}
    all_months = [f"{year}-{m:02d}" for m in range(1, 13)]

    for region_id in sorted(alerts_by_region):
        items = alerts_by_region[region_id]
        count = len(items)
        total_hours = sum(item["duration_hours"] for item in items)
        longest_hours = max(item["duration_hours"] for item in items)
        night_count = sum(1 for item in items if 0 <= item["started"].hour < 6)
        night_share = (night_count / count) * 100.0
        avg_minutes = (total_hours * 60.0) / count

        monthly_counts: dict[str, int] = defaultdict(int)
        monthly_hours: dict[str, float] = defaultdict(float)
        for item in items:
            period = item["started"].strftime("%Y-%m")
            monthly_counts[period] += 1
            monthly_hours[period] += item["duration_hours"]

        observed_months = sorted(monthly_counts.keys())
        months_count = len(observed_months)
        missing_months = [m for m in all_months if m not in monthly_counts]
        max_date = max(item["started"].date().isoformat() for item in items)
        is_complete = int(months_count == 12 and max_date == f"{year}-12-31")

        per_month = count / months_count
        hours_per_month = total_hours / months_count

        coverage_meta[region_id] = {
            "alerts_max_date": max_date,
            "alerts_months_count": months_count,
            "alerts_missing_months": ";".join(missing_months),
            "alerts_complete_2025": is_complete,
        }

        metric_values = {
            "alerts_count": count,
            "alerts_hours": round(total_hours, 2),
            "alerts_longest_hours": round(longest_hours, 2),
            "alerts_night_share": round(night_share, 2),
            "alerts_avg_minutes": round(avg_minutes, 2),
            "alerts_per_month": round(per_month, 2),
            "alerts_hours_per_month": round(hours_per_month, 2),
        }

        for metric_id in ALERTS_METRIC_IDS:
            metrics_rows.append(
                {
                    "region_id": region_id,
                    "metric_id": metric_id,
                    "value": metric_values[metric_id],
                    "value_text": "",
                    "year": year,
                }
            )

        for period in observed_months:
            series_rows.append(
                {
                    "region_id": region_id,
                    "metric_id": "alerts_count",
                    "period": period,
                    "value": monthly_counts[period],
                }
            )
            series_rows.append(
                {
                    "region_id": region_id,
                    "metric_id": "alerts_hours",
                    "period": period,
                    "value": round(monthly_hours[period], 2),
                }
            )

    return metrics_rows, series_rows, coverage_meta


def build_alerts_catalog(year: int = 2025) -> list[dict]:
    """Повертає каталог метрик тривог із коректними одиницями виміру."""
    source_name = "Повітряні тривоги (Vadimkin/ukrainian-air-raid-sirens-dataset)"
    source_url = "https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset"
    return [
        {
            "id": "alerts_count",
            "title_uk": "Кількість повітряних тривог",
            "unit": f"тривог за спостережуваний період {year}",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_hours",
            "title_uk": "Сумарна тривалість тривог",
            "unit": f"годин за спостережуваний період {year}",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_longest_hours",
            "title_uk": "Найдовша тривога",
            "unit": "годин",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_night_share",
            "title_uk": "Частка нічних тривог (00–06)",
            "unit": "%",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_avg_minutes",
            "title_uk": "Середня тривалість тривоги",
            "unit": "хвилин",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_per_month",
            "title_uk": "Інтенсивність тривог на місяць",
            "unit": "тривог / спост. місяць",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
        {
            "id": "alerts_hours_per_month",
            "title_uk": "Тривалість тривог на місяць",
            "unit": "годин / спост. місяць",
            "kind": "numeric",
            "category": "war",
            "source_name": source_name,
            "source_url": source_url,
            "year": year,
            "higher_is": "worse",
        },
    ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _rank_alerts_metrics(metrics_rows: list[dict]) -> list[dict]:
    """Додає rank (1 = найбільше значення) та n_ranked для метрик тривог."""
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for row in metrics_rows:
        by_metric[row["metric_id"]].append(row)

    ranked_rows: list[dict] = []
    for metric_id in ALERTS_METRIC_IDS:
        group = by_metric.get(metric_id, [])
        values = [float(r["value"]) for r in group]
        n_ranked = len(group)
        for r in group:
            val = float(r["value"])
            rank = 1 + sum(1 for other in values if other > val)
            ranked_rows.append(
                {
                    **r,
                    "rank": rank,
                    "n_ranked": n_ranked,
                }
            )
    return ranked_rows


def rebuild_parsed_outputs(
    catalog_rows: list[dict],
    alerts_metrics: list[dict],
    alerts_series: list[dict],
    coverage_meta: dict[str, dict],
) -> None:
    """Оновлює parts/alerts_*.csv та фінальні CSV у data/parsed/, не чіпаючи інші модулі."""
    _write_csv(
        PARTS_DIR / "alerts_catalog.csv",
        ["id", "title_uk", "unit", "kind", "category", "source_name", "source_url", "year", "higher_is"],
        catalog_rows,
    )
    _write_csv(
        PARTS_DIR / "alerts_metrics.csv",
        ["region_id", "metric_id", "value", "value_text", "year"],
        alerts_metrics,
    )
    _write_csv(
        PARTS_DIR / "alerts_series.csv",
        ["region_id", "metric_id", "period", "value"],
        alerts_series,
    )

    # 1. metrics.csv: замінюємо лише alerts_*-рядки, решту зберігаємо без змін
    metrics_path = PARSED_DIR / "metrics.csv"
    with metrics_path.open(encoding="utf-8", newline="") as f:
        existing_metrics = [r for r in csv.DictReader(f) if not r["id"].startswith("alerts_")]
    _write_csv(
        metrics_path,
        ["id", "title_uk", "unit", "kind", "category", "source_name", "source_url", "year", "higher_is"],
        catalog_rows + existing_metrics,
    )

    # 2. region_metrics.csv: замінюємо лише alerts_*-рядки з перерахованими rank/n_ranked
    rm_path = PARSED_DIR / "region_metrics.csv"
    with rm_path.open(encoding="utf-8", newline="") as f:
        existing_rm = [r for r in csv.DictReader(f) if not r["metric_id"].startswith("alerts_")]
    ranked_alerts = _rank_alerts_metrics(alerts_metrics)
    _write_csv(
        rm_path,
        ["region_id", "metric_id", "value", "value_text", "year", "rank", "n_ranked"],
        ranked_alerts + existing_rm,
    )

    # 3. series.csv: замінюємо лише alerts_*-рядки, решту (demography) зберігаємо без змін
    series_path = PARSED_DIR / "series.csv"
    with series_path.open(encoding="utf-8", newline="") as f:
        existing_series = [r for r in csv.DictReader(f) if not r["metric_id"].startswith("alerts_")]
    _write_csv(
        series_path,
        ["region_id", "metric_id", "period", "value"],
        alerts_series + existing_series,
    )

    # 4. coverage.csv: оновлюємо прапорці alerts_*, total та додаємо метадані повноти 2025 року
    cov_path = PARSED_DIR / "coverage.csv"
    with cov_path.open(encoding="utf-8", newline="") as f:
        cov_reader = csv.DictReader(f)
        old_fields = cov_reader.fieldnames or []
        cov_rows = list(cov_reader)

    non_alert_metric_cols = [
        c
        for c in old_fields
        if c not in ("region_id", "total", "alerts_max_date", "alerts_months_count", "alerts_missing_months", "alerts_complete_2025")
        and not c.startswith("alerts_")
    ]
    all_metric_cols = sorted(non_alert_metric_cols + list(ALERTS_METRIC_IDS))
    new_fields = [
        "region_id",
        *all_metric_cols,
        "total",
        "alerts_max_date",
        "alerts_months_count",
        "alerts_missing_months",
        "alerts_complete_2025",
    ]

    alerts_present_regions = set(coverage_meta.keys())
    updated_cov: list[dict] = []
    for row in cov_rows:
        rid = row["region_id"]
        has_alerts = 1 if rid in alerts_present_regions else 0
        new_row: dict[str, object] = {"region_id": rid}
        for col in non_alert_metric_cols:
            new_row[col] = row[col]
        for col in ALERTS_METRIC_IDS:
            new_row[col] = has_alerts

        new_row["total"] = sum(int(new_row[col]) for col in all_metric_cols)
        meta = coverage_meta.get(rid)
        if meta:
            new_row.update(meta)
        else:
            new_row.update(
                {
                    "alerts_max_date": "",
                    "alerts_months_count": 0,
                    "alerts_missing_months": ";".join(f"2025-{m:02d}" for m in range(1, 13)),
                    "alerts_complete_2025": 0,
                }
            )
        updated_cov.append(new_row)

    _write_csv(cov_path, new_fields, updated_cov)


class AlertsStep(Step):
    """Крок ETL поверх тих самих функцій; rank/n_ranked перераховує run_all."""

    name = "alerts"

    def __init__(self, year: int = 2025):
        self.year = year

    def run(self, ctx: EtlContext) -> EtlTables:
        region_map = load_region_map(ctx.parsed_dir / "regions.csv")
        alerts_by_region, _ = parse_deduplicated_alerts(ctx.data_dir / "alerts" / "official_data_uk.csv",
                                                        region_map, year=self.year)
        metrics_rows, series_rows, _ = compute_alerts_data(alerts_by_region, year=self.year)
        return EtlTables(
            metrics=[metric_from_row(r) for r in build_alerts_catalog(year=self.year)],
            region_metrics=[region_metric_from_row(r) for r in metrics_rows],
            series=[series_from_row(r) for r in series_rows],
        )


def main() -> None:
    """Запускає повний цикл парсингу тривог 2025 року та оновлення data/parsed/."""
    region_map = load_region_map(PARSED_DIR / "regions.csv")
    alerts_by_region, stats = parse_deduplicated_alerts(ALERTS_CSV, region_map, year=2025)
    alerts_metrics, alerts_series, coverage_meta = compute_alerts_data(alerts_by_region, year=2025)
    catalog_rows = build_alerts_catalog(year=2025)

    rebuild_parsed_outputs(catalog_rows, alerts_metrics, alerts_series, coverage_meta)
    print(
        f"Готово: raw_2025={stats['raw_year_rows']}, "
        f"dedup_2025={stats['dedup_year_rows']}, "
        f"regions={len(alerts_by_region)}, "
        f"series_rows={len(alerts_series)}"
    )


if __name__ == "__main__":
    main()
