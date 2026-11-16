"""Держстат: data/drats/sssu_{birth,mortality,marriage_divorce}.json.gz (SDMX). Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv):
  births, births_per_1000, mother_age_avg, deaths_per_birth,
  marriages, divorces, marriages_per_1000, divorces_per_1000, divorces_per_100_marriages,
  deaths, deaths_per_1000 + помісячні серії (births, deaths).
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path

from app.domain import EtlTables, MetricInfo, RegionMetric, SeriesPoint
from etl.base import EtlContext, Step

BIRTH_SOURCE = "Держстат: Народжуваність (SDMX DF_POPULATION_BIRTH)"
BIRTH_URL = "https://data.gov.ua/dataset/8ce892f8-a4c4-4c17-bdcf-b0537e2d2de4"
MORT_SOURCE = "Держстат: Смертність (SDMX DF_POPULATION_MORTALITY)"
MORT_URL = "https://data.gov.ua/dataset/93984cf9-6ec4-4846-9bc8-2a25075abdad"
MARR_SOURCE = "Держстат: Шлюбність і розлучуваність (SDMX DF_POPULATION_MARRIAGE_DIVORCE)"
MARR_URL = "https://data.gov.ua/dataset/4f458054-6c66-468e-b47c-414ae1e98975"

DRATS_YEAR = 2021

DRATS_METRICS: list[MetricInfo] = [
    MetricInfo("births", "Кількість живонароджених", "осіб за рік", "numeric", "demography", BIRTH_SOURCE, BIRTH_URL, DRATS_YEAR, "neutral"),
    MetricInfo("births_per_1000", "Народжуваність", "на 1000 мешканців", "numeric", "demography", BIRTH_SOURCE, BIRTH_URL, DRATS_YEAR, "better"),
    MetricInfo("mother_age_avg", "Середній вік матері при народженні дитини", "років", "numeric", "demography", BIRTH_SOURCE, BIRTH_URL, DRATS_YEAR, "neutral"),
    MetricInfo("deaths_per_birth", "Померлих на одного народженого", "осіб", "numeric", "demography", BIRTH_SOURCE, BIRTH_URL, DRATS_YEAR, "worse"),
    MetricInfo("marriages", "Кількість зареєстрованих шлюбів", "за рік", "numeric", "demography", MARR_SOURCE, MARR_URL, DRATS_YEAR, "neutral"),
    MetricInfo("divorces", "Кількість розірвань шлюбів", "за рік", "numeric", "demography", MARR_SOURCE, MARR_URL, DRATS_YEAR, "neutral"),
    MetricInfo("marriages_per_1000", "Шлюбність", "на 1000 мешканців", "numeric", "demography", MARR_SOURCE, MARR_URL, DRATS_YEAR, "neutral"),
    MetricInfo("divorces_per_1000", "Розлучуваність", "на 1000 мешканців", "numeric", "demography", MARR_SOURCE, MARR_URL, DRATS_YEAR, "worse"),
    MetricInfo("divorces_per_100_marriages", "Розлучень на 100 шлюбів", "на 100 шлюбів", "numeric", "demography", MARR_SOURCE, MARR_URL, DRATS_YEAR, "worse"),
    MetricInfo("deaths", "Кількість померлих", "осіб за рік", "numeric", "demography", MORT_SOURCE, MORT_URL, DRATS_YEAR, "neutral"),
    MetricInfo("deaths_per_1000", "Смертність", "на 1000 мешканців", "numeric", "demography", MORT_SOURCE, MORT_URL, DRATS_YEAR, "worse"),
]

_ANNUAL_CODES: dict[str, dict[str, str]] = {
    "sssu_birth.json.gz": {"PNMI_17": "births", "PNMI_32": "births_per_1000", "PNMI_3344": "mother_age_avg"},
    "sssu_mortality.json.gz": {"PNMI_19": "deaths", "PNMI_46": "deaths_per_1000"},
    "sssu_marriage_divorce.json.gz": {
        "PNMI_28": "marriages",
        "PNMI_31": "divorces",
        "PNMI_62": "marriages_per_1000",
        "PNMI_63": "divorces_per_1000",
    },
}

_MONTHLY_CODES: dict[str, dict[str, str]] = {
    "sssu_birth.json.gz": {"PNMI_17": "births"},
    "sssu_mortality.json.gz": {"PNMI_19": "deaths"},
}


def _extract_sdmx(
    path: Path,
    koatuu_to_region: dict[str, str],
    annual_map: dict[str, str],
    monthly_map: dict[str, str],
    year: int = DRATS_YEAR,
) -> tuple[dict[tuple[str, str], float], list[SeriesPoint]]:
    """Читає SDMX JSON.gz, повертає (region_id, metric_id) -> value та місячні серії."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)

    struct = payload["data"]["structures"][0]
    s_dims = struct["dimensions"]["series"]
    o_dims = struct["dimensions"].get("observation", [])
    time_vals = [v.get("id") or v.get("value") for v in o_dims[0]["values"]]
    time_idx_to_period: dict[str, str] = {}
    for idx, t_val in enumerate(time_vals):
        if t_val == str(year):
            time_idx_to_period[str(idx)] = str(year)
        elif isinstance(t_val, str) and t_val.startswith(f"{year}-M"):
            month = t_val.split("-M", 1)[1]
            time_idx_to_period[str(idx)] = f"{year}-{month}"

    annual_values: dict[tuple[str, str], float] = {}
    series_points: list[SeriesPoint] = []
    ds = payload["data"]["dataSets"][0]["series"]

    for key, body in ds.items():
        parts = key.split(":")
        labels = {s_dims[i]["id"]: s_dims[i]["values"][int(p)]["id"] for i, p in enumerate(parts)}
        ind = labels.get("INDICATOR", "")
        freq = labels.get("FREQ", "A")
        reg_code = labels.get("REGION", "")

        if not reg_code.startswith("UA") or reg_code == "UA00000000000000000":
            continue
        region_id = koatuu_to_region.get(reg_code[2:4])
        if not region_id:
            continue

        # Беремо лише тотальні зрізи (усі додаткові виміри == _T або _Z)
        if any(
            val not in ("_T", "_Z")
            for dim_id, val in labels.items()
            if dim_id not in ("INDICATOR", "REGION", "FREQ")
        ):
            continue

        obs = body.get("observations", {})
        if freq == "A" and ind in annual_map:
            metric_id = annual_map[ind]
            for t_idx, period in time_idx_to_period.items():
                if period == str(year) and t_idx in obs and obs[t_idx][0] is not None:
                    annual_values[(region_id, metric_id)] = float(obs[t_idx][0])
        elif freq == "M" and ind in monthly_map:
            metric_id = monthly_map[ind]
            for t_idx, period in time_idx_to_period.items():
                if "-" in period and t_idx in obs and obs[t_idx][0] is not None:
                    series_points.append(SeriesPoint(region_id, metric_id, period, float(obs[t_idx][0])))

    return annual_values, series_points


class DratsStep(Step):
    name = "drats"

    def run(self, ctx: EtlContext) -> EtlTables:
        drats_dir = ctx.data_dir / "drats"
        koatuu_to_region = {r.koatuu2: r.id for r in ctx.regions.values() if r.koatuu2}

        values: dict[tuple[str, str], float] = {}
        series: list[SeriesPoint] = []
        for filename, annual_map in _ANNUAL_CODES.items():
            monthly_map = _MONTHLY_CODES.get(filename, {})
            v, s = _extract_sdmx(drats_dir / filename, koatuu_to_region, annual_map, monthly_map)
            values.update(v)
            series.extend(s)

        # Похідні метрики на основі базових
        by_reg: dict[str, dict[str, float]] = defaultdict(dict)
        for (rid, mid), val in values.items():
            by_reg[rid][mid] = val

        for rid, m in by_reg.items():
            if m.get("births") and "deaths" in m:
                values[(rid, "deaths_per_birth")] = round(m["deaths"] / m["births"], 3)
            if m.get("marriages") and "divorces" in m:
                values[(rid, "divorces_per_100_marriages")] = round((m["divorces"] / m["marriages"]) * 100.0, 3)

        region_metrics = [
            RegionMetric(region_id=rid, metric_id=mid, value=val, year=DRATS_YEAR)
            for (rid, mid), val in sorted(values.items())
        ]
        return EtlTables(metrics=list(DRATS_METRICS), region_metrics=region_metrics,
                         series=_monthly_from_cumulative(series))


def _monthly_from_cumulative(points: list[SeriesPoint]) -> list[SeriesPoint]:
    """Держстат дає помісячні значення наростаючим підсумком з початку року (грудень == річне).
    Переводимо в значення за кожен місяць: v[m] - v[m-1]."""
    by_key: dict[tuple[str, str], list[SeriesPoint]] = defaultdict(list)
    for p in points:
        by_key[(p.region_id, p.metric_id)].append(p)
    out: list[SeriesPoint] = []
    for (rid, mid), pts in sorted(by_key.items()):
        prev = 0.0
        for p in sorted(pts, key=lambda x: x.period):
            out.append(SeriesPoint(rid, mid, p.period, p.value - prev))
            prev = p.value
    return out
