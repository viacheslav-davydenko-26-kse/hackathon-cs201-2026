"""Synthetic regressions for raw-clue compatibility; no files or database writes."""
from __future__ import annotations

import json
import math

import pytest

from app.domain import MetricInfo, RegionInfo, RegionMetric
from etl.build_facts import DefaultFactGenerator, facts_from_rows


def numeric_catalog(*metric_ids: str) -> dict[str, dict]:
    return {
        mid: {
            "title_uk": "Показник", "unit": "годин",
            "kind": "numeric", "category": "war",
        }
        for mid in metric_ids
    }


def observation(region_id: str, value: int | float | None) -> dict:
    return {
        "region_id": region_id, "value": value, "value_text": "",
        "year": 2025, "rank": None, "n_ranked": None,
    }


def raw_facts(values: list[int | float | None]) -> list[dict]:
    rows = [observation(f"r{i}", value) for i, value in enumerate(values)]
    return [
        fact for fact in facts_from_rows(numeric_catalog("x"), {"x": rows})
        if fact["kind"] == "raw"
    ]


@pytest.mark.parametrize("values,displayed,groups", [
    pytest.param(
        [5.55, 5.55, 6.2], ["5.55", "5.55", "6.20"],
        [["r0", "r1"], ["r0", "r1"], ["r2"]], id="exact-ties",
    ),
    pytest.param(
        [5.551, 5.554, 5.556], ["5.55", "5.55", "5.56"],
        [["r0", "r1"], ["r0", "r1"], ["r2"]], id="rounded-collision-and-boundary",
    ),
    pytest.param(
        [7, 7.0, 8], ["7", "7", "8"],
        [["r0", "r1"], ["r0", "r1"], ["r2"]], id="integer-float-equivalence",
    ),
    pytest.param(
        [0, 0.0, None], ["0", "0"],
        [["r0", "r1"], ["r0", "r1"]], id="zero-is-observed-not-missing",
    ),
    pytest.param(
        [1_000_000, 1_000_001, 2_000_000], ["1\u00a0000\u00a0000", "1\u00a0000\u00a0001", "2\u00a0000\u00a0000"],
        [["r0"], ["r1"], ["r2"]], id="large-integers-keep-all-digits",
    ),
    pytest.param(
        [1234.5, 1234.504, 99.0], ["1\u00a0234.50", "1\u00a0234.50", "99"],
        [["r0", "r1"], ["r0", "r1"], ["r2"]], id="thousands-separator-in-decimals",
    ),
])
def test_raw_sets_match_displayed_values(values, displayed, groups):
    # Expected strings/sets are explicit; do not reuse the production formatter.
    facts = raw_facts(values)
    assert len(facts) == len(displayed)
    for i, (fact, text, compatible) in enumerate(zip(facts, displayed, groups)):
        assert fact["region_id"] == f"r{i}"
        assert fact["text_uk"] == f"Показник: {text} годин"
        assert json.loads(fact["consistent"]) == compatible
        assert fact["region_id"] in compatible


def test_missing_value_generates_no_fact_and_is_not_compatible():
    rows = [observation("missing", None), observation("a", 5.551), observation("b", 5.554)]
    facts = facts_from_rows(numeric_catalog("x"), {"x": rows})
    assert facts
    assert all(fact["region_id"] != "missing" for fact in facts)
    assert all("missing" not in json.loads(fact["consistent"]) for fact in facts)
    raw = [fact for fact in facts if fact["kind"] == "raw"]
    assert len(raw) == 2
    assert all(json.loads(fact["consistent"]) == ["a", "b"] for fact in raw)


def test_all_missing_values_generate_no_facts():
    assert facts_from_rows(
        numeric_catalog("x"), {"x": [observation("a", None), observation("b", None)]},
    ) == []


def test_compatibility_is_isolated_by_metric_even_with_identical_text():
    rows = {
        "x": [observation("a", 5.551), observation("b", 5.554)],
        "y": [observation("c", 5.551)],
    }
    facts = facts_from_rows(numeric_catalog("x", "y"), rows)
    raw = {(fact["metric_id"], fact["region_id"]): fact for fact in facts if fact["kind"] == "raw"}
    assert set(raw) == {("x", "a"), ("x", "b"), ("y", "c")}
    assert len({fact["text_uk"] for fact in raw.values()}) == 1
    assert json.loads(raw["x", "a"]["consistent"]) == ["a", "b"]
    assert json.loads(raw["x", "b"]["consistent"]) == ["a", "b"]
    assert json.loads(raw["y", "c"]["consistent"]) == ["c"]


def test_information_score_uses_the_full_displayed_compatibility_set():
    facts = raw_facts([5.55, 5.551, 5.554, 8])
    assert len(facts) == 4
    for fact in facts[:3]:
        assert len(json.loads(fact["consistent"])) == 3
        assert fact["info"] == pytest.approx(math.log2(25 / 3), rel=0, abs=0.0005)
    assert facts[3]["info"] == pytest.approx(math.log2(25), rel=0, abs=0.0005)
    assert facts[0]["info"] < facts[3]["info"]


def test_raw_sets_are_deterministic_and_sorted_when_input_order_changes():
    rows = [observation("z", 5.551), observation("a", 5.554), observation("m", 9)]
    catalog = numeric_catalog("x")
    first = facts_from_rows(catalog, {"x": rows})
    assert first == facts_from_rows(catalog, {"x": rows})
    forward = {fact["region_id"]: fact for fact in first if fact["kind"] == "raw"}
    reverse = {
        fact["region_id"]: fact
        for fact in facts_from_rows(catalog, {"x": rows[::-1]}) if fact["kind"] == "raw"
    }
    assert forward == reverse
    assert json.loads(forward["z"]["consistent"]) == ["a", "z"]


def test_generator_excludes_nonplayable_regions_from_raw_sets():
    regions = [
        RegionInfo("a", "Область A", "A", True),
        RegionInfo("b", "Область B", "B", True),
        RegionInfo("disabled", "Неігровий регіон", "Неігровий", False),
    ]
    metrics = [MetricInfo("x", "Показник", "годин", "numeric", "war")]
    values = [RegionMetric(rid, "x", val) for rid, val in (
        ("a", 5.551), ("b", 5.554), ("disabled", 5.552),
    )]
    facts = DefaultFactGenerator().generate(regions, metrics, values)
    raw = {fact.region_id: fact for fact in facts if fact.kind == "raw"}
    assert set(raw) == {"a", "b"}
    for fact in raw.values():
        assert fact.consistent == frozenset({"a", "b"})
        assert fact.text_uk == "Показник: 5.55 годин"
