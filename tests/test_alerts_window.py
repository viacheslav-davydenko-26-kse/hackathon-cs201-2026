"""Спільне вікно тривог (docs/contract.md §9 A1–A7). Власник: Ілля; розширює Вадім."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.repository import CsvRepository
from etl.base import EtlContext
from etl.load_alerts import (
    ALERTS_METRIC_IDS, alerts_window, build_alerts_catalog, compute_alerts_data, full_months, max_quiet_days,
    window_label,
)

KYIV = ZoneInfo("Europe/Kyiv")


def alert(day: str, hour: int = 12, hours: float = 1.0) -> dict:
    started = datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=KYIV)
    return {"started": started, "finished": started, "duration_hours": hours}


@pytest.fixture
def uneven():
    """a: дані до 31.03; b: до 15.02 (обрив) — вікно має закінчитись 15.02."""
    return {
        "a": [alert("2025-01-10"), alert("2025-02-10"), alert("2025-02-20"), alert("2025-03-31")],
        "b": [alert("2025-01-05"), alert("2025-02-15", hour=2)],
        "empty": [],
    }


def test_a1_window_ends_at_earliest_last_record(uneven):
    assert alerts_window(uneven) == (date(2025, 1, 1), date(2025, 2, 15))


def test_a1_a4_values_only_inside_window(uneven):
    rows, _, coverage = compute_alerts_data(uneven)
    values = {(r["region_id"], r["metric_id"]): r["value"] for r in rows}
    assert values[("a", "alerts_count")] == 2          # 20.02 і 31.03 поза вікном
    assert values[("b", "alerts_count")] == 2
    assert values[("b", "alerts_night_share")] == 50.0
    assert not any(rid == "empty" for rid, _ in values)
    assert {(c["alerts_window_start"], c["alerts_window_end"]) for c in coverage.values()} == \
           {("2025-01-01", "2025-02-15")}


def test_a2_window_uses_kyiv_start_date():
    # 23:30 UTC 15.02 = 01:30 16.02 за Києвом → поза вікном, що закінчується 15.02
    late = {"started": datetime(2025, 2, 15, 23, 30, tzinfo=ZoneInfo("UTC")).astimezone(KYIV),
            "finished": None, "duration_hours": 1.0}
    data = {"a": [alert("2025-01-02"), late], "b": [alert("2025-01-03"), alert("2025-02-15")]}
    rows, _, _ = compute_alerts_data(data)
    assert {(r["region_id"], r["metric_id"]): r["value"] for r in rows}[("a", "alerts_count")] == 1


def test_a5_series_only_full_months_with_zeros(uneven):
    _, series, _ = compute_alerts_data(uneven)
    periods = {s["period"] for s in series}
    assert periods == {"2025-01"}                       # лютий обрізаний — не входить
    assert full_months((date(2025, 1, 1), date(2025, 3, 31))) == ["2025-01", "2025-02", "2025-03"]
    _, series, _ = compute_alerts_data({"a": [alert("2025-02-03"), alert("2025-03-31")],
                                        "b": [alert("2025-03-31")]})
    jan = [s for s in series if s["region_id"] == "b" and s["period"] == "2025-01"]
    assert [s["value"] for s in jan] == [0, 0]          # count і hours: місяць без тривог = 0


def test_a3_units_name_the_window():
    assert window_label((date(2025, 1, 1), date(2025, 7, 31))) == "січень–липень 2025"
    assert window_label((date(2025, 1, 1), date(2025, 1, 31))) == "січень 2025"
    assert window_label((date(2025, 1, 1), date(2025, 8, 20))) == "1 січня – 20 серпня 2025"
    units = {r["id"]: r["unit"] for r in build_alerts_catalog(2025, (date(2025, 1, 1), date(2025, 8, 20)))}
    assert units["alerts_count"] == "тривог за період 1 січня – 20 серпня 2025"
    assert "рік" not in units["alerts_hours"]


def test_a6_no_per_month_metrics():
    assert not [m for m in ALERTS_METRIC_IDS if "per_month" in m]


def test_a7_quiet_gap_detection():
    items = [alert("2025-01-01"), alert("2025-01-02"), alert("2025-01-20")]
    assert max_quiet_days(items, (date(2025, 1, 1), date(2025, 1, 31))) == (17, "2025-01-03")


def test_parsed_data_follows_window_rules():
    parsed = CsvRepository(EtlContext().parsed_dir)
    units = {m.id: m.unit for m in parsed.metrics() if m.id.startswith("alerts_")}
    assert set(units) == set(ALERTS_METRIC_IDS)
    assert "рік" not in units["alerts_count"] and "рік" not in units["alerts_hours"]
    periods = {s.period for r in parsed.regions() for s in parsed.series(r.id, "alerts_count")}
    assert periods == {f"2025-{m:02d}" for m in range(1, 8)}   # повні місяці вікна 01.01–20.08
    assert not parsed.region_metrics("luhansk", "alerts_count")
