"""Якість підказок: короткі, конкретні, чесні `consistent`, без повторів категорії підряд."""
from __future__ import annotations

import json
import math
import random
import re

import pytest

from app.game.hints import SPECIFIC_MAX_CONSISTENT, FactHintPicker, order_hints, pick_hints_from_list
from etl.build_facts import RELATIVE_BANDS, facts_from_rows, relative_band

MAX_HINT_LEN = 80


def _rows(values: dict[str, float]) -> list[dict]:
    return [{"region_id": rid, "value": v, "value_text": "", "year": 2025, "rank": None, "n_ranked": None}
            for rid, v in values.items()]


def _relative(values: dict[str, float]) -> dict[str, dict]:
    catalog = {"x": {"title_uk": "Показник", "unit": "", "kind": "numeric", "category": "war"}}
    return {f["region_id"]: f for f in facts_from_rows(catalog, {"x": _rows(values)}) if f["kind"] == "relative"}


def _stated_interval(text: str) -> tuple[float, float]:
    """Прочитати з тексту, що саме стверджується (так, як прочитає гравець), → [lo, hi) у % від середнього."""
    for lo, hi, phrase in RELATIVE_BANDS:
        if text.endswith(phrase):
            return lo, hi
    raise AssertionError(f"unknown relative phrase: {text!r}")


# ------------------------------------------------------------------ relative: текст == consistent
def test_bands_cover_the_line_without_gaps():
    for (_, hi, _), (lo, _, _) in zip(RELATIVE_BANDS, RELATIVE_BANDS[1:]):
        assert hi == lo
    assert RELATIVE_BANDS[0][0] == -math.inf and RELATIVE_BANDS[-1][1] == math.inf


@pytest.mark.parametrize("pct,expected", [(-5, "в межах ±5%"), (4.999, "в межах ±5%"), (5, "на 5–20% вище"),
                                          (-5.001, "на 5–20% нижче"), (100, "у 2–3 рази")])
def test_band_boundaries_are_half_open(pct, expected):
    assert expected in RELATIVE_BANDS[relative_band(100 + pct, 100)][2]


def test_relative_consistent_is_exactly_the_regions_the_text_is_true_for():
    # середнє ≈ 100.17: a, b, c у межах ±5%; d = +8% — старий текст «±10%» охоплював би й d, а set — ні
    values = {"a": 100, "b": 96, "c": 104.9, "d": 108, "e": 70, "f": 122.1}
    assert sum(values.values()) / len(values) == pytest.approx(100.1666, abs=1e-3)
    facts = _relative(values)
    avg = sum(values.values()) / len(values)
    for rid, fact in facts.items():
        lo, hi = _stated_interval(fact["text_uk"])
        true_for = {r for r, v in values.items() if lo <= (v - avg) / avg * 100 < hi}
        assert set(json.loads(fact["consistent"])) == true_for, fact["text_uk"]


def test_relative_text_does_not_claim_wider_range_than_its_set():
    for fact in _relative({"a": 100, "b": 109, "c": 91, "d": 100}).values():
        assert "±10%" not in fact["text_uk"]


# ------------------------------------------------------------------ лаконічність
def test_all_real_facts_are_short(repo):
    for region in repo.playable_regions():
        for fact in repo.facts(region.id):
            assert len(fact.text_uk) <= MAX_HINT_LEN, fact.text_uk
            assert "«" not in fact.text_uk and "по Україні" not in fact.text_uk, fact.text_uk


def test_alert_raw_hint_names_its_window_not_a_year(repo):
    raw = [f for f in repo.facts("lviv") if f.metric_id == "alerts_count" and f.kind == "raw"]
    assert raw and re.search(r"\(1 січня – \d+ \w+ 20\d\d\)", raw[0].text_uk), raw


# ------------------------------------------------------------------ підбір
def _fact(rid, metric, cat, cons, info=None):
    cons = sorted(cons)
    return {"region_id": rid, "metric_id": metric, "kind": "relative", "text_uk": f"{metric}", "category": cat,
            "consistent": json.dumps(cons), "info": info if info is not None else math.log2(25 / len(cons))}


def test_order_avoids_adjacent_categories_when_possible():
    chosen = [_fact("t", "a", "war", "t", 0.1), _fact("t", "b", "war", "t", 0.2),
              _fact("t", "c", "demography", "t", 0.3), _fact("t", "d", "demography", "t", 0.4),
              _fact("t", "e", "education", "t", 0.5)]
    ordered = order_hints(chosen)
    assert all(a["category"] != b["category"] for a, b in zip(ordered, ordered[1:]))


def test_picker_prefers_specific_facts_and_alternates_categories():
    universe = [f"r{i}" for i in range(25)]
    facts = [_fact("r0", "wide1", "war", universe[:20]), _fact("r0", "wide2", "war", universe[:18]),
             _fact("r0", "m1", "war", universe[:10]), _fact("r0", "m2", "demography", universe[:8] + ["r20"]),
             _fact("r0", "m3", "education", ["r0", "r1", "r2", "r3", "r9"]),
             _fact("r0", "m4", "demography", ["r0", "r1", "r5"]), _fact("r0", "m5", "education", ["r0"]),
             _fact("r0", "m6", "war", ["r0", "r2"])]
    for seed in range(30):
        hints = pick_hints_from_list("r0", facts, n=5, seed=seed)
        assert len(hints) == 5
        assert not {h["metric_id"] for h in hints} & {"wide1", "wide2"}
        assert all(a["category"] != b["category"] for a, b in zip(hints, hints[1:]))


def test_real_rounds_are_specific_unique_and_alternate(repo):
    picker = FactHintPicker(repo)
    for region in repo.playable_regions():
        facts = {(f.metric_id, f.text_uk): f for f in repo.facts(region.id)}
        available = {f.category for f in facts.values()}
        for seed in range(5):
            hints = picker.pick(region.id, rng=random.Random(seed))
            used = [facts[(h.metric_id, h.text)] for h in hints]
            assert frozenset.intersection(*(f.consistent for f in used)) == {region.id}
            assert all(len(f.consistent) <= SPECIFIC_MAX_CONSISTENT for f in used), region.id
            if len(available) >= 2:
                assert all(a.category != b.category for a, b in zip(hints, hints[1:])), region.id
            assert len({h.metric_id for h in hints}) == 5
