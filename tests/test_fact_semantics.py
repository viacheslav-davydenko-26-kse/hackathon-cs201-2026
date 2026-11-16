"""Independent fact truth and hint contract checks with small synthetic data."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from app.domain import Fact, RegionInfo
from app.errors import DataUnavailable
from app.game.hints import FactHintPicker
from app.repository import InMemoryRepository, SqliteRepository
from etl.build_facts import facts_from_rows


def row(region, value=None, rank=None, text="", n=5):
    return {"region_id": region, "value": value, "value_text": text,
            "rank": rank, "n_ranked": n, "year": 2025}


def generate(rows, kind="numeric"):
    catalog = {"x": {"title_uk": "Показник", "unit": "одиниць",
                     "kind": kind, "category": "education"}}
    return facts_from_rows(catalog, {"x": rows})


def test_rank_fact_sets_include_all_regions_satisfying_the_claim():
    facts = generate([row("a", 50, 1), row("b", 40, 2), row("c", 40, 2),
                      row("d", 20, 4), row("e", 10, 5)])
    ranks = {f["region_id"]: f for f in facts if f["kind"] == "rank"}
    assert set(ranks) == {"a", "b", "c", "d", "e"}
    for rid in ("b", "c"):
        assert "топ-3" in ranks[rid]["text_uk"]
        assert set(json.loads(ranks[rid]["consistent"])) == {"a", "b", "c"}
    assert set(json.loads(ranks["a"]["consistent"])) == {"a"}
    for rid in ("d", "e"):
        assert set(json.loads(ranks[rid]["consistent"])) == {"d", "e"}


def test_categorical_fact_sets_follow_equal_observed_values():
    facts = generate([row("a", text="фізика"), row("b", text="біологія"),
                      row("c", text="фізика"), row("missing")], kind="categorical")
    assert len(facts) == 3
    expected = {"a": {"a", "c"}, "b": {"b"}, "c": {"a", "c"}}
    for fact in facts:
        assert fact["kind"] == "categorical"
        assert set(json.loads(fact["consistent"])) == expected[fact["region_id"]]


def test_within_ten_percent_claim_includes_every_region_within_ten_percent():
    # Mean = 100. All three values satisfy the literal displayed ±10% claim.
    facts = generate([row("a", 94), row("b", 100), row("c", 106)])
    center = next(f for f in facts if f["kind"] == "relative" and f["region_id"] == "b")
    assert "±10%" in center["text_uk"]
    assert set(json.loads(center["consistent"])) == {"a", "b", "c"}, (
        "Compatible sets must match the displayed claim, not a narrower internal bucket"
    )


def synthetic_repo(facts):
    return InMemoryRepository(
        regions=[RegionInfo("a", "Область A", "A", True),
                 RegionInfo("b", "Область B", "B", True)],
        facts=facts,
    )


def fact(index, compatible=frozenset({"a"}), category="war"):
    return Fact("a", f"m{index}", "raw", f"Числова підказка {index}",
                compatible, 1.0, category=category)


@pytest.mark.parametrize("scenario", ["empty", "insufficient", "ambiguous"])
def test_picker_explicitly_rejects_unsolvable_synthetic_rounds(scenario):
    facts = {
        "empty": [],
        "insufficient": [fact(i) for i in range(4)],
        "ambiguous": [fact(i, frozenset({"a", "b"})) for i in range(5)],
    }[scenario]
    with pytest.raises(DataUnavailable):
        FactHintPicker(synthetic_repo(facts)).pick("a", rng=random.Random(42))


def test_picker_does_not_repeat_adjacent_categories_when_ordering_is_feasible():
    # Equal information permits war/demography/education/war/demography order.
    categories = ["war", "demography", "education"] * 2
    picker = FactHintPicker(synthetic_repo([fact(i, category=c) for i, c in enumerate(categories)]))
    violations = []
    for seed in range(10):
        hints = picker.pick("a", rng=random.Random(seed))
        assert len(hints) == 5
        if any(a.category == b.category for a, b in zip(hints, hints[1:])):
            violations.append((seed, [h.category for h in hints]))
    assert not violations, f"Adjacent category repetition despite feasible alternatives: {violations}"


@pytest.mark.parametrize("seed", [0, 42, 2026])
def test_real_picker_is_deterministic_and_orders_hints_by_information(seed):
    repo = SqliteRepository(Path(__file__).resolve().parents[1] / "db/game.sqlite")
    picker = FactHintPicker(repo)
    for region in repo.playable_regions():
        first = picker.pick(region.id, rng=random.Random(seed))
        assert first == picker.pick(region.id, rng=random.Random(seed))
        assert [h.index for h in first] == list(range(5))
        source = {(f.metric_id, f.riddle_uk or f.text_uk): f for f in repo.facts(region.id)}
        selected = [source[h.metric_id, h.text] for h in first]
        assert [f.info for f in selected] == sorted(f.info for f in selected)
        assert set.intersection(*(set(f.consistent) for f in selected)) == {region.id}

