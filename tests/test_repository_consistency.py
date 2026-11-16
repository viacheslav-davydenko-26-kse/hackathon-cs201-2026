"""Read-only freshness/parity checks of shipped SQLite and parsed CSV data."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

import pytest

from app.repository import CsvRepository, SqliteRepository
from etl.build_facts import DefaultFactGenerator


@pytest.fixture(scope="module")
def repositories():
    root = Path(__file__).resolve().parents[1]
    return CsvRepository(root / "data/parsed"), SqliteRepository(root / "db/game.sqlite")


@pytest.mark.parametrize("table", ["regions", "metrics"])
def test_sqlite_registry_and_catalog_match_csv(repositories, table):
    csv, sqlite = repositories
    expected = getattr(csv, table)()
    actual = getattr(sqlite, table)()
    assert expected and actual
    assert Counter(actual) == Counter(expected)


def test_sqlite_observations_match_csv_including_missingness_and_years(repositories):
    csv, sqlite = repositories
    # SQLite recomputes competition ranks; older CSV ordinal ranks are not the
    # authority for ties. All source values, years and missing cells must match.
    def observations(repo):
        return Counter(replace(r, rank=None, n_ranked=None) for r in repo.region_metrics())
    assert csv.region_metrics() and sqlite.region_metrics()
    assert observations(sqlite) == observations(csv)
    categorical = {m.id for m in csv.metrics() if m.kind == "categorical"}
    assert categorical
    for observation in sqlite.region_metrics():
        if observation.metric_id in categorical:
            assert observation.value is None and observation.value_text


def test_sqlite_competition_ranks_follow_numeric_values(repositories):
    _, sqlite = repositories
    playable = {r.id for r in sqlite.playable_regions()}
    catalog = {m.id: m for m in sqlite.metrics()}
    by_metric = defaultdict(list)
    for row in sqlite.region_metrics():
        by_metric[row.metric_id].append(row)
    for mid, rows in by_metric.items():
        numeric = [r.value for r in rows if catalog[mid].kind == "numeric"
                   and r.region_id in playable and r.value is not None]
        for row in rows:
            if catalog[mid].kind == "numeric" and row.region_id in playable and row.value is not None:
                assert row.rank == 1 + sum(value > row.value for value in numeric), (mid, row)
                assert row.n_ranked == len(numeric), (mid, row)
            else:
                assert row.rank is None and row.n_ranked is None, (mid, row)


def test_sqlite_monthly_series_match_csv_with_no_lost_or_duplicate_points(repositories):
    csv, sqlite = repositories
    def points(repo):
        return Counter(point for region in repo.regions() for point in repo.series(region.id))
    assert points(csv)
    assert points(sqlite) == points(csv)


def test_shipped_facts_match_current_generator_without_regenerating_database(repositories):
    _, sqlite = repositories
    generated = DefaultFactGenerator().generate(
        sqlite.regions(), sqlite.metrics(), sqlite.region_metrics(),
    )
    stored = sqlite.facts()
    assert generated and stored
    expected = Counter(replace(f, id=None) for f in generated)
    actual = Counter(replace(f, id=None) for f in stored)
    missing = list((expected - actual).elements())
    stale = list((actual - expected).elements())
    assert not missing and not stale, (
        f"Shipped facts are stale: {len(missing)} missing/current and {len(stale)} obsolete; "
        f"examples: missing={missing[:2]}, obsolete={stale[:2]}"
    )
