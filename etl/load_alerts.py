"""Тривоги (level == 'oblast') -> region_metrics + series + coverage.

Покриття джерела нерівне (див. docs/contract.md §9 A1–A6): усі метрики рахуються лише
у СПІЛЬНОМУ вікні `alerts_window()`, щоб регіони порівнювались на однаковому періоді.

Власник: Ілля.

Два входи до одних і тих самих функцій:
  * `python -m etl.load_alerts` — перезаписує data/parsed/*.csv (alerts_*-рядки);
  * `AlertsStep` — крок для `python -m etl.run_all --source raw` (нічого не пише, повертає EtlTables).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
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
)

#: Метадані покриття в data/parsed/coverage.csv (не метрики).
COVERAGE_META = ("alerts_max_date", "alerts_months_count", "alerts_missing_months", "alerts_complete_2025",
                 "alerts_window_start", "alerts_window_end", "alerts_max_quiet_days", "alerts_max_quiet_from")

MONTHS_UK = ("січень", "лютий", "березень", "квітень", "травень", "червень",
             "липень", "серпень", "вересень", "жовтень", "листопад", "грудень")

#: Пауза без жодної тривоги довша за це (у межах вікна) — попередження в etl.check:
#: за даними не відрізнити тихий період від пропуску в джерелі.
MAX_QUIET_DAYS = 14


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


def alerts_window(alerts_by_region: dict[str, list[dict]], year: int = 2025) -> tuple[date, date]:
    """Спільне вікно порівняння: з 1 січня до НАЙРАНІШОЇ останньої дати серед регіонів з даними.

    Джерело обривається в різних регіонів у різні дні (Хмельницька — 20.08, Київ — 31.12).
    Відсутні дні не можна вважати нулем, тож усі регіони порівнюємо лише на періоді,
    який покритий у всіх. Регіони без жодного запису (Луганська) у вікно не впливають.
    """
    last_dates = [max(i["started"].date() for i in items) for items in alerts_by_region.values() if items]
    if not last_dates:
        raise ValueError("no alert records")
    return date(year, 1, 1), min(last_dates)


def window_label(window: tuple[date, date]) -> str:
    """'січень–липень 2025' / 'січень 2025' / '1 січня – 20 серпня 2025' (якщо межі не по місяцях)."""
    start, end = window
    full_last_month = (end + timedelta(days=1)).day == 1
    if start.day == 1 and full_last_month:
        a, b = MONTHS_UK[start.month - 1], MONTHS_UK[end.month - 1]
        return f"{a} {end.year}" if a == b else f"{a}–{b} {end.year}"
    gen = ("січня", "лютого", "березня", "квітня", "травня", "червня",
           "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")
    return f"{start.day} {gen[start.month - 1]} – {end.day} {gen[end.month - 1]} {end.year}"


def full_months(window: tuple[date, date]) -> list[str]:
    """Календарні місяці, що повністю лежать у вікні (лише вони йдуть у помісячні серії)."""
    start, end = window
    out, m = [], date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        if m >= start and nxt - timedelta(days=1) <= end:
            out.append(m.strftime("%Y-%m"))
        m = nxt
    return out


def max_quiet_days(items: list[dict], window: tuple[date, date]) -> tuple[int, str]:
    """Найдовша пауза без тривог у вікні (днів) і дата її початку."""
    days = sorted({i["started"].date() for i in items if window[0] <= i["started"].date() <= window[1]})
    points = [window[0] - timedelta(days=1)] + days + [window[1] + timedelta(days=1)]
    gap, at = max(((b - a).days - 1, a) for a, b in zip(points, points[1:]))
    return gap, (at + timedelta(days=1)).isoformat()


def compute_alerts_data(
    alerts_by_region: dict[str, list[dict]],
    year: int = 2025,
    window: tuple[date, date] | None = None,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """Метрики, помісячні серії та метадані покриття — ЛИШЕ в межах спільного вікна.

    window=None → alerts_window(alerts_by_region, year). Тривога належить вікну за датою
    початку (Europe/Kyiv). Серії — лише за повні місяці вікна (без «обрізаного» останнього).
    """
    window = window or alerts_window(alerts_by_region, year)
    series_months = set(full_months(window))
    metrics_rows: list[dict] = []
    series_rows: list[dict] = []
    coverage_meta: dict[str, dict] = {}
    all_months = [f"{year}-{m:02d}" for m in range(1, 13)]

    for region_id in sorted(alerts_by_region):
        all_items = alerts_by_region[region_id]
        if not all_items:
            continue
        observed = sorted({i["started"].strftime("%Y-%m") for i in all_items})
        max_date = max(i["started"].date() for i in all_items).isoformat()
        quiet, quiet_from = max_quiet_days(all_items, window)
        coverage_meta[region_id] = {
            "alerts_max_date": max_date,
            "alerts_months_count": len(observed),
            "alerts_missing_months": ";".join(m for m in all_months if m not in observed),
            "alerts_complete_2025": int(len(observed) == 12 and max_date == f"{year}-12-31"),
            "alerts_window_start": window[0].isoformat(),
            "alerts_window_end": window[1].isoformat(),
            "alerts_max_quiet_days": quiet,
            "alerts_max_quiet_from": quiet_from,
        }

        items = [i for i in all_items if window[0] <= i["started"].date() <= window[1]]
        if not items:
            continue
        count = len(items)
        total_hours = sum(item["duration_hours"] for item in items)
        metric_values = {
            "alerts_count": count,
            "alerts_hours": round(total_hours, 2),
            "alerts_longest_hours": round(max(item["duration_hours"] for item in items), 2),
            "alerts_night_share": round(sum(1 for i in items if 0 <= i["started"].hour < 6) / count * 100.0, 2),
            "alerts_avg_minutes": round(total_hours * 60.0 / count, 2),
        }
        for metric_id in ALERTS_METRIC_IDS:
            metrics_rows.append({"region_id": region_id, "metric_id": metric_id,
                                 "value": metric_values[metric_id], "value_text": "", "year": year})

        monthly_counts: dict[str, int] = defaultdict(int)
        monthly_hours: dict[str, float] = defaultdict(float)
        for item in items:
            period = item["started"].strftime("%Y-%m")
            if period in series_months:
                monthly_counts[period] += 1
                monthly_hours[period] += item["duration_hours"]
        for period in sorted(series_months):
            series_rows.append({"region_id": region_id, "metric_id": "alerts_count",
                                "period": period, "value": monthly_counts.get(period, 0)})
            series_rows.append({"region_id": region_id, "metric_id": "alerts_hours",
                                "period": period, "value": round(monthly_hours.get(period, 0.0), 2)})

    return metrics_rows, series_rows, coverage_meta


def build_alerts_catalog(year: int = 2025, window: tuple[date, date] | None = None) -> list[dict]:
    """Каталог метрик тривог. Одиниці кількісних метрик називають вікно порівняння."""
    label = window_label(window) if window else str(year)
    period = f"за період {label}" if label[0].isdigit() and " – " in label else f"за {label}"
    source_name = "Повітряні тривоги (Vadimkin/ukrainian-air-raid-sirens-dataset)"
    source_url = "https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset"
    rows = [
        ("alerts_count", "Кількість повітряних тривог", f"тривог {period}"),
        ("alerts_hours", "Сумарна тривалість тривог", f"годин {period}"),
        ("alerts_longest_hours", "Найдовша тривога", "годин"),
        ("alerts_night_share", "Частка нічних тривог (00–06)", "%"),
        ("alerts_avg_minutes", "Середня тривалість тривоги", "хвилин"),
    ]
    return [{"id": mid, "title_uk": title, "unit": unit, "kind": "numeric", "category": "war",
             "source_name": source_name, "source_url": source_url, "year": year, "higher_is": "worse"}
            for mid, title, unit in rows]


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
        if c not in ("region_id", "total", *COVERAGE_META)
        and not c.startswith("alerts_")
    ]
    all_metric_cols = sorted(non_alert_metric_cols + list(ALERTS_METRIC_IDS))
    new_fields = [
        "region_id",
        *all_metric_cols,
        "total",
        *COVERAGE_META,
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
            new_row.update({k: "" for k in COVERAGE_META})
            new_row.update({"alerts_months_count": 0, "alerts_complete_2025": 0,
                            "alerts_missing_months": ";".join(f"2025-{m:02d}" for m in range(1, 13))})
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
        window = alerts_window(alerts_by_region, year=self.year)
        metrics_rows, series_rows, _ = compute_alerts_data(alerts_by_region, year=self.year, window=window)
        return EtlTables(
            metrics=[metric_from_row(r) for r in build_alerts_catalog(year=self.year, window=window)],
            region_metrics=[region_metric_from_row(r) for r in metrics_rows],
            series=[series_from_row(r) for r in series_rows],
        )


def main() -> None:
    """Запускає повний цикл парсингу тривог 2025 року та оновлення data/parsed/."""
    region_map = load_region_map(PARSED_DIR / "regions.csv")
    alerts_by_region, stats = parse_deduplicated_alerts(ALERTS_CSV, region_map, year=2025)
    window = alerts_window(alerts_by_region, year=2025)
    alerts_metrics, alerts_series, coverage_meta = compute_alerts_data(alerts_by_region, year=2025, window=window)
    catalog_rows = build_alerts_catalog(year=2025, window=window)

    rebuild_parsed_outputs(catalog_rows, alerts_metrics, alerts_series, coverage_meta)
    print(
        f"Готово: raw_2025={stats['raw_year_rows']}, "
        f"dedup_2025={stats['dedup_year_rows']}, "
        f"regions={len(alerts_by_region)}, "
        f"series_rows={len(alerts_series)}, "
        f"window={window[0]}..{window[1]} ({window_label(window)})"
    )


if __name__ == "__main__":
    main()
