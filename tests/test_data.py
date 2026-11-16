"""Read-only data checks and an in-memory alert-loader regression; no downloads.

Raw source duplicates are allowed, but must not inflate processed aggregates.
Missing data is represented by absent observations or blank CSV cells, never
inferred to be zero. Annual coverage is outside this suite's scope.
"""

import csv
import io
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


DATA = Path(__file__).resolve().parents[1] / "data"
KYIV_TIME = ZoneInfo("Europe/Kyiv")
EXPECTED_REGIONS = {
    "vinnytsia", "volyn", "dnipro", "donetsk", "zhytomyr", "zakarpattia",
    "zaporizhzhia", "ivano_frankivsk", "kyiv_obl", "kirovohrad", "luhansk",
    "lviv", "mykolaiv", "odesa", "poltava", "rivne", "sumy", "ternopil",
    "kharkiv", "kherson", "khmelnytskyi", "cherkasy", "chernivtsi",
    "chernihiv", "kyiv_city", "crimea", "sevastopol",
}
COUNT_METRICS = {
    "alerts_count", "births", "deaths", "marriages", "divorces",
    "population", "nmt_participants",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames, f"{path.name}: missing CSV header"
        assert len(reader.fieldnames) == len(set(reader.fieldnames)), (
            f"{path.name}: duplicate column names"
        )
        rows = list(reader)
    assert rows, f"{path.name}: unexpectedly empty dataset"
    assert all(None not in row and None not in row.values() for row in rows), (
        f"{path.name}: rows do not match the CSV header"
    )
    return rows


def has_value(row):
    # In particular, "0" is present, while "" is missing.
    return bool(row["value"].strip() or row.get("value_text", "").strip())


def number(value, context):
    try:
        result = float(value)
    except (TypeError, ValueError):
        pytest.fail(f"{context}: expected a number, got {value!r}")
    assert math.isfinite(result), f"{context}: nonfinite value {value!r}"
    return result


def assert_unique(rows, fields, context):
    counts = Counter(tuple(row[field] for field in fields) for row in rows)
    duplicates = [(key, count) for key, count in counts.items() if count > 1]
    assert not duplicates, f"{context}: duplicate keys (first 10): {duplicates[:10]}"


@pytest.fixture(scope="module")
def tables():
    return {
        name: read_csv(DATA / "parsed" / f"{name}.csv")
        for name in ("regions", "metrics", "region_metrics", "series", "coverage")
    }


@pytest.fixture(scope="module")
def raw_oblast_alerts():
    rows = read_csv(DATA / "alerts" / "official_data_uk.csv")
    alerts = [row for row in rows if row["level"] == "oblast"]
    assert alerts, "Raw alerts contain no oblast-level records"
    return alerts


# 1. Preserve raw source snapshots; verify that the real loader removes duplicates.
def test_alert_loader_ignores_duplicate_events():
    from etl.load_alerts import compute_alerts_data, parse_deduplicated_alerts

    fields = ("oblast", "level", "started_at", "finished_at", "source")
    events = [
        ("Львівська область", "oblast", "2025-01-01T08:00:00+00:00",
         "2025-01-01T09:00:00+00:00", "official"),
        ("Львівська область", "oblast", "2025-01-01T10:00:00+00:00",
         "2025-01-01T12:00:00+00:00", "official"),
        ("м. Київ", "oblast", "2025-01-01T08:00:00+00:00",
         "2025-01-01T08:30:00+00:00", "official"),
    ]
    region_map = {"Львівська область": "lviv", "м. Київ": "kyiv_city"}

    class InMemoryCsv:
        """Supply Path.open's input stream without creating a fixture file."""

        def __init__(self, rows):
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
            self.text = stream.getvalue()

        def open(self, **kwargs):
            return io.StringIO(self.text, newline="")

    clean, _ = parse_deduplicated_alerts(InMemoryCsv(events), region_map, year=2025)
    repeated, stats = parse_deduplicated_alerts(
        InMemoryCsv(events + [events[0], events[2], events[0]]),
        region_map,
        year=2025,
    )
    assert stats["raw_year_rows"] == 6
    assert stats["dedup_year_rows"] == 3
    assert {rid: len(items) for rid, items in repeated.items()} == {
        "lviv": 2, "kyiv_city": 1,
    }
    expected_outputs = compute_alerts_data(clean, year=2025)
    actual_outputs = compute_alerts_data(repeated, year=2025)
    assert actual_outputs == expected_outputs, "Duplicates changed metrics, series or coverage"
    values = {
        (row["region_id"], row["metric_id"]): row["value"]
        for row in actual_outputs[0]
    }
    for key, expected in {
        ("lviv", "alerts_count"): 2,
        ("lviv", "alerts_hours"): 3,
        ("kyiv_city", "alerts_count"): 1,
        ("kyiv_city", "alerts_hours"): 0.5,
    }.items():
        assert values[key] == pytest.approx(expected), key


# 2. Recalculate independently from unique source events, using UTC durations
# and Kyiv-local start years. Local wall-clock subtraction is wrong across DST.
@pytest.mark.parametrize("metric_id", ["alerts_count", "alerts_hours"])
def test_alert_aggregates_match_unique_events(tables, raw_oblast_alerts, metric_id):
    catalog = {row["id"]: row for row in tables["metrics"]}
    assert metric_id in catalog, f"Missing required metric {metric_id}"
    year = int(catalog[metric_id]["year"])
    # docs/contract.md §9 A1: aggregates cover only the shared comparison window.
    windows = {(row["alerts_window_start"], row["alerts_window_end"])
               for row in tables["coverage"] if row["alerts_window_start"]}
    assert len(windows) == 1, f"Regions disagree on the alerts window: {windows}"
    (window_start, window_end), = windows
    names = {row["name_uk"]: row["id"] for row in tables["regions"]}
    names["м.Київ"] = "kyiv_city"
    counts = Counter()
    durations = defaultdict(list)
    seen = set()
    for row in raw_oblast_alerts:
        key = tuple(row[field] for field in (
            "oblast", "started_at", "finished_at", "source"
        ))
        if key in seen:
            continue
        seen.add(key)
        start = datetime.fromisoformat(row["started_at"])
        assert start.utcoffset() is not None, f"Alert lacks timezone: {key}"
        local_day = start.astimezone(KYIV_TIME).date().isoformat()
        if start.astimezone(KYIV_TIME).year != year or not row["finished_at"]:
            continue
        if not window_start <= local_day <= window_end:
            continue
        assert row["oblast"] in names, f"Unknown raw region: {row['oblast']!r}"
        end = datetime.fromisoformat(row["finished_at"])
        assert end.utcoffset() is not None, f"Alert lacks timezone: {key}"
        hours = (end.timestamp() - start.timestamp()) / 3600
        assert hours >= 0, f"Alert ends before it starts: {key}"
        region_id = names[row["oblast"]]
        counts[region_id] += 1
        durations[region_id].append(hours)

    assert counts, f"No completed source events found for {year}"
    actual = {
        row["region_id"]: number(row["value"], f"{row['region_id']}/{metric_id}")
        for row in tables["region_metrics"] if row["metric_id"] == metric_id
    }
    assert actual.keys() == counts.keys(), (
        f"{metric_id}: source/output region mismatch: "
        f"missing={sorted(counts.keys() - actual.keys())}, "
        f"extra={sorted(actual.keys() - counts.keys())}"
    )
    mismatches = []
    for region_id, count in counts.items():
        expected = count if metric_id == "alerts_count" else math.fsum(durations[region_id])
        tolerance = 0 if metric_id == "alerts_count" else 0.005001
        if abs(actual[region_id] - expected) > tolerance:
            mismatches.append((region_id, actual[region_id], round(expected, 6)))
    assert not mismatches, (
        f"{metric_id}: (region, stored, deduplicated expected): {mismatches}"
    )


# 4. Foreign keys and uniqueness at the existing CSV interface.
@pytest.mark.parametrize("table,fields", [
    ("regions", ("id",)),
    ("metrics", ("id",)),
    ("region_metrics", ("region_id", "metric_id")),
    ("series", ("region_id", "metric_id", "period")),
    ("coverage", ("region_id",)),
])
def test_processed_keys_are_unique(tables, table, fields):
    assert_unique(tables[table], fields, table)


def test_metric_and_series_references_exist(tables):
    regions = {row["id"] for row in tables["regions"]}
    metrics = {row["id"] for row in tables["metrics"]}
    for table in ("region_metrics", "series"):
        for row in tables[table]:
            assert row["region_id"] in regions, f"{table}: orphan region {row}"
            assert row["metric_id"] in metrics, f"{table}: orphan metric {row}"


# 5. IDs, playability and map metadata must agree; centroids need not lie inside
# a concave polygon, so containment is deliberately not required.
def test_region_registry_and_kyiv_are_correct(tables):
    regions = {row["id"]: row for row in tables["regions"]}
    assert set(regions) == EXPECTED_REGIONS
    assert all(row["playable"] in {"0", "1"} for row in regions.values())
    assert {rid for rid, row in regions.items() if row["playable"] == "1"} == (
        EXPECTED_REGIONS - {"crimea", "sevastopol"}
    )
    for field in ("iso", "koatuu2"):
        assert_unique(tables["regions"], (field,), "region codes")
        assert all(row[field].strip() for row in regions.values())
    for rid, iso, koatuu in (("kyiv_city", "UA-30", "80"), ("kyiv_obl", "UA-32", "32")):
        assert regions[rid]["iso"] == iso
        assert regions[rid]["koatuu2"] == koatuu
    assert regions["kyiv_city"]["name_en"] == "Kyiv"
    assert regions["kyiv_obl"]["name_en"] == "Kyiv Oblast"
    for rid, row in regions.items():
        assert -90 <= number(row["lat"], f"{rid}/lat") <= 90
        assert -180 <= number(row["lon"], f"{rid}/lon") <= 180
        assert number(row["area_km2"], f"{rid}/area") > 0


def test_map_matches_region_registry(tables):
    with (DATA / "parsed" / "ua.geojson").open(encoding="utf-8") as stream:
        geojson = json.load(stream)
    assert geojson["type"] == "FeatureCollection"
    features = geojson["features"]
    regions = {row["id"]: row for row in tables["regions"]}
    ids = [feature["properties"]["region_id"] for feature in features]
    assert len(ids) == len(set(ids)) == 27
    assert set(ids) == set(regions)
    for feature in features:
        assert feature["type"] == "Feature"
        properties = feature["properties"]
        region = regions[properties["region_id"]]
        for field in ("name_uk", "short_uk", "playable"):
            assert str(properties[field]) == region[field], properties
        geometry = feature["geometry"]
        assert geometry["type"] in {"Polygon", "MultiPolygon"}
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        assert polygons, f"Empty geometry: {properties}"
        for polygon in polygons:
            assert polygon, f"Polygon has no rings: {properties}"
            for ring in polygon:
                assert len(ring) >= 4 and ring[0] == ring[-1], properties
                for point in ring:
                    assert len(point) == 2, properties
                    assert -180 <= number(point[0], "map longitude") <= 180
                    assert -90 <= number(point[1], "map latitude") <= 90


# 6. Validate observed values without filling gaps or treating missing as zero.
def test_metric_values_have_valid_types_and_ranges(tables):
    catalog = {row["id"]: row for row in tables["metrics"]}
    assert all(row["kind"] in {"numeric", "categorical"} for row in catalog.values())
    for row in tables["region_metrics"]:
        mid = row["metric_id"]
        context = f"{row['region_id']}/{mid}"
        assert has_value(row), f"{context}: empty observation; omit missing observations"
        definition = catalog[mid]
        if definition["kind"] == "categorical":
            assert not row["value"].strip() and row["value_text"].strip(), context
            assert row["value_text"].strip().lower() not in {"null", "nan", "none"}, context
            continue
        assert row["value"].strip() and not row["value_text"].strip(), context
        value = number(row["value"], context)
        assert value >= 0, context
        if mid in COUNT_METRICS:
            assert value.is_integer(), f"{context}: fractional count {value}"
        if "%" in definition["unit"]:
            assert value <= 100, f"{context}: percentage exceeds 100"
        if mid.startswith("nmt_avg_"):
            assert 100 <= value <= 200, context


def test_series_values_and_periods_are_valid(tables):
    for row in tables["series"]:
        context = f"{row['region_id']}/{row['metric_id']}/{row['period']}"
        try:
            period = datetime.strptime(row["period"], "%Y-%m")
        except ValueError:
            pytest.fail(f"{context}: invalid month")
        assert period.strftime("%Y-%m") == row["period"], context
        value = number(row["value"], context)
        assert value >= 0, context
        if row["metric_id"] in COUNT_METRICS:
            assert value.is_integer(), f"{context}: fractional count {value}"


# 7. Coverage must describe both numeric and categorical observations exactly.
def test_coverage_matches_observations(tables):
    region_ids = {row["id"] for row in tables["regions"]}
    metric_ids = {row["id"] for row in tables["metrics"]}
    coverage = tables["coverage"]
    assert {row["region_id"] for row in coverage} == region_ids
    metadata_columns = {
        "alerts_max_date", "alerts_months_count",
        "alerts_missing_months", "alerts_complete_2025",
        "alerts_window_start", "alerts_window_end",
        "alerts_max_quiet_days", "alerts_max_quiet_from",
    }
    assert not metric_ids & metadata_columns, "Coverage metadata conflicts with metric IDs"
    assert set(coverage[0]) == metric_ids | {"region_id", "total"} | metadata_columns
    present = {
        (row["region_id"], row["metric_id"])
        for row in tables["region_metrics"] if has_value(row)
    }
    for row in coverage:
        expected_total = 0
        for mid in metric_ids:
            expected = int((row["region_id"], mid) in present)
            assert row[mid] in {"0", "1"}, f"Invalid coverage flag: {row['region_id']}/{mid}"
            assert int(row[mid]) == expected, f"Wrong coverage: {row['region_id']}/{mid}"
            expected_total += expected
        assert row["total"] == str(expected_total), f"Wrong coverage total: {row['region_id']}"


# 8. Recalculate from source metrics; allow only the published 3-decimal rounding.
@pytest.mark.parametrize("derived,numerator,denominator,factor", [
    ("deaths_per_birth", "deaths", "births", 1),
    ("divorces_per_100_marriages", "divorces", "marriages", 100),
    ("nmt_participants_per_1000", "nmt_participants", "population", 1000),
])
def test_derived_metrics_match_inputs(tables, derived, numerator, denominator, factor):
    values = {
        (row["region_id"], row["metric_id"]): row
        for row in tables["region_metrics"]
    }
    assert any(mid == derived for _, mid in values), f"Missing derived metric: {derived}"
    for region in tables["regions"]:
        rid = region["id"]
        output = values.get((rid, derived))
        num = values.get((rid, numerator))
        den = values.get((rid, denominator))
        available = num is not None and den is not None and num["value"].strip() and den["value"].strip()
        if not available or number(den["value"], f"{rid}/{denominator}") == 0:
            assert output is None or not has_value(output), f"{rid}/{derived}: missing/zero input"
            continue
        assert output is not None and output["value"].strip(), f"Missing {rid}/{derived}"
        expected = factor * number(num["value"], numerator) / number(den["value"], denominator)
        assert number(output["value"], derived) == pytest.approx(expected, rel=0, abs=0.000500001), (
            f"{rid}/{derived}: does not match {numerator}/{denominator}"
        )


def test_region_population_matches_population_metric(tables):
    population = {
        row["region_id"]: row for row in tables["region_metrics"]
        if row["metric_id"] == "population"
    }
    for region in tables["regions"]:
        rid = region["id"]
        observation = population.get(rid)
        if observation is None or not observation["value"].strip():
            assert not region["population"].strip(), f"{rid}: unsupported population"
        else:
            value = number(region["population"], f"{rid}/population")
            assert value >= 0 and value.is_integer(), rid
            assert value == number(observation["value"], f"{rid}/population metric"), rid
