"""Збирає db/game.sqlite і static/ua.geojson з нуля.  Власник: Ілля.

    python -m etl.run_all                 # з data/parsed (швидко, працює вже зараз)
    python -m etl.run_all --source raw    # із сирих файлів через load_*.py
"""
from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import replace

from app.domain import EtlTables
from etl.base import EtlContext, Step, compute_ranks, validate, write_db
from etl.build_facts import DefaultFactGenerator
from etl.build_geo import build_geo
from etl.load_alerts import AlertsStep
from etl.load_cars import CarsStep
from etl.load_drats import DratsStep
from etl.load_nmt import NmtStep
from etl.load_parsed import ParsedCsvStep
from etl.load_population import load_population
from etl.regions import load_regions

SOURCES: dict[str, list[Step]] = {
    "parsed": [ParsedCsvStep()],
    "raw": [AlertsStep(), DratsStep(), CarsStep(), NmtStep()],
}


def log(msg: str) -> None:
    print(f"[etl] {msg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser().parse_known_args(argv)[1]
    source = args[args.index("--source") + 1] if "--source" in args else "parsed"
    ctx = EtlContext()
    regions = list(load_regions(ctx.parsed_dir / "regions.csv"))

    try:
        pop = load_population(ctx)
        regions = [replace(r, population=pop[r.id][0], area_km2=pop[r.id][1]) if r.id in pop else r for r in regions]
    except NotImplementedError:
        log("load_population: not implemented, using data/parsed/regions.csv")
    ctx.regions = {r.id: r for r in regions}

    try:
        centroids = build_geo(ctx)
        regions = [replace(r, lat=centroids[r.id][0], lon=centroids[r.id][1]) if r.id in centroids else r
                   for r in regions]
    except NotImplementedError:
        log("build_geo: not implemented, copying data/parsed/ua.geojson")
        shutil.copyfile(ctx.parsed_dir / "ua.geojson", ctx.static_dir / "ua.geojson")
    ctx.regions = {r.id: r for r in regions}

    tables = EtlTables()
    for step in SOURCES[source]:
        try:
            out = step.run(ctx)
            log(f"{step.name}: {len(out.metrics)} metrics, {len(out.region_metrics)} values, {len(out.series)} points")
            tables.extend(out)
        except NotImplementedError as e:
            log(f"{step.name}: SKIPPED ({e})")

    metrics = {m.id: m for m in tables.metrics}
    tables.region_metrics = compute_ranks(tables.region_metrics, metrics, only=set(ctx.playable_ids))
    if problems := validate(tables, set(ctx.regions)):
        log("validation failed:\n  " + "\n  ".join(problems))
        return 1

    try:
        facts = DefaultFactGenerator().generate(regions, tables.metrics, tables.region_metrics)
        log(f"facts: {len(facts)}")
    except NotImplementedError as e:
        facts = []
        log(f"facts: SKIPPED ({e})")

    write_db(ctx.db_path, ctx.schema_path, regions, tables, facts)
    log(f"wrote {ctx.db_path.relative_to(ctx.db_path.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
