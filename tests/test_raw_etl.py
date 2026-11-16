"""Сирі ETL-кроки дають ті самі значення, що й data/parsed/*.csv. Власник: Ілля.

НМТ розпаковує 7z і читає ~300 тис. рядків (~12 с), тому позначений `slow`:  pytest -m slow
"""
import pytest

from app.repository import CsvRepository
from etl.base import EtlContext
from etl.load_alerts import AlertsStep
from etl.load_drats import DratsStep
from etl.load_nmt import NmtStep
from etl.load_population import PopulationStep, load_population
from etl.regions import load_regions


@pytest.fixture(scope="module")
def ctx():
    c = EtlContext()
    c.regions = {r.id: r for r in load_regions()}
    return c


@pytest.fixture(scope="module")
def parsed():
    return CsvRepository(EtlContext().parsed_dir)


def assert_matches_parsed(step, ctx, parsed):
    out = step.run(ctx)
    ids = {m.id for m in out.metrics}
    want_metrics = {m.id: m for m in parsed.metrics() if m.id in ids}
    assert {m.id: m for m in out.metrics} == want_metrics
    got = {(r.region_id, r.metric_id): (r.value, r.value_text) for r in out.region_metrics}
    want = {(r.region_id, r.metric_id): (r.value, r.value_text) for r in parsed.region_metrics() if r.metric_id in ids}
    assert got == want
    got_s = {(s.region_id, s.metric_id, s.period, s.value) for s in out.series}
    want_s = {(s.region_id, s.metric_id, s.period, s.value)
              for r in parsed.regions() for s in parsed.series(r.id) if s.metric_id in ids}
    assert got_s == want_s


@pytest.mark.parametrize("step", [PopulationStep(), AlertsStep(), DratsStep()], ids=lambda s: s.name)
def test_step_matches_parsed(step, ctx, parsed):
    assert_matches_parsed(step, ctx, parsed)


@pytest.mark.slow
def test_nmt_matches_parsed(ctx, parsed):
    assert_matches_parsed(NmtStep(), ctx, parsed)


def test_load_population_matches_regions(ctx):
    pop = load_population(ctx)
    assert {rid: p for rid, (p, _) in pop.items()} == \
           {r.id: r.population for r in ctx.regions.values() if r.population is not None}
