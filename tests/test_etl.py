"""ETL-каркас: нормалізація назв, ранги, валідація. Власник: Ілля."""
import pytest

from app.domain import EtlTables, MetricInfo, RegionMetric
from etl.base import compute_ranks, validate
from etl.regions import UnknownRegion, normalize_region


@pytest.mark.parametrize("raw,rid", [
    ("Львівська обл.", "lviv"), ("м.Київ", "kyiv_city"), ("м. Київ", "kyiv_city"), ("Kyiv", "kyiv_city"),
    ("Київська область", "kyiv_obl"), ("Kyiv Oblast", "kyiv_obl"), ("UA-46", "lviv"),
    ("Вінницькa область", "vinnytsia"),  # латинська «a»
    ("Iвано-Франківська", "ivano_frankivsk"),  # латинська «I»
    ("АР Крим", "crimea"),
])
def test_normalize_region(raw, rid):
    assert normalize_region(raw) == rid


def test_unknown_region():
    with pytest.raises(UnknownRegion):
        normalize_region("Марс")


def test_ranks_ties():
    m = {"x": MetricInfo(id="x", title_uk="x", unit=None, kind="numeric", category="war")}
    rows = [RegionMetric(r, "x", v) for r, v in [("a", 5), ("b", 3), ("c", 3), ("d", 1), ("e", None)]]
    ranks = {r.region_id: (r.rank, r.n_ranked) for r in compute_ranks(rows, m)}
    assert ranks == {"a": (1, 4), "b": (2, 4), "c": (2, 4), "d": (4, 4), "e": (None, None)}


def test_validate_catches_undeclared_metric():
    t = EtlTables(region_metrics=[RegionMetric("lviv", "ghost", 1.0)])
    assert any("undeclared" in p for p in validate(t, {"lviv"}))
