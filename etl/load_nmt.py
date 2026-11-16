"""НМТ: data/nmt/OpenDataNMT2025.7z. Власник: Ілля.

Метрики (id мають збігатися з data/parsed/metrics.csv):
  nmt_participants, nmt_participants_per_1000, nmt_avg_{ukr,math,hist},
  nmt_180_{ukr,math,hist}, nmt_any_180_share, nmt_eng_share,
  nmt_top_elective (categorical), nmt_top_elective_non_eng (categorical).
"""
from __future__ import annotations

import csv
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from app.domain import EtlTables, MetricInfo, RegionMetric
from etl.base import EtlContext, Step
from etl.regions import normalize_region

NMT_SOURCE = "УЦОЯО: Відкриті дані НМТ"
NMT_URL = "https://zno.testportal.com.ua/opendata"
NMT_YEAR = 2025

NMT_METRICS: list[MetricInfo] = [
    MetricInfo("nmt_participants", "Кількість учасників НМТ", "осіб", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "neutral"),
    MetricInfo("nmt_participants_per_1000", "Учасників НМТ на 1000 мешканців", "на 1000 мешканців", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "neutral"),
    MetricInfo("nmt_avg_ukr", "Середній бал НМТ: українська мова", "балів (100–200)", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_180_ukr", "Частка 180+ балів: українська мова", "% зарахованих", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_avg_math", "Середній бал НМТ: математика", "балів (100–200)", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_180_math", "Частка 180+ балів: математика", "% зарахованих", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_avg_hist", "Середній бал НМТ: історія України", "балів (100–200)", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_180_hist", "Частка 180+ балів: історія України", "% зарахованих", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_any_180_share", "Частка учасників з 180+ хоча б з одного предмета", "%", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "better"),
    MetricInfo("nmt_eng_share", "Частка учасників, що обрали англійську", "%", "numeric", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "neutral"),
    MetricInfo("nmt_top_elective", "Найпопулярніший предмет на вибір", None, "categorical", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "neutral"),
    MetricInfo("nmt_top_elective_non_eng", "Найпопулярніший предмет на вибір, крім англійської", None, "categorical", "education", NMT_SOURCE, NMT_URL, NMT_YEAR, "neutral"),
]

_ELECTIVES: tuple[tuple[str, str], ...] = (
    ("PhysBlockStatus", "фізика"),
    ("ChemBlockStatus", "хімія"),
    ("BioBlockStatus", "біологія"),
    ("GeoBlockStatus", "географія"),
    ("EngBlockStatus", "англійська мова"),
    ("FraBlockStatus", "французька мова"),
    ("DeuBlockStatus", "німецька мова"),
    ("SpaBlockStatus", "іспанська мова"),
    ("UkrLitBlockStatus", "українська література"),
)

_SKIP_REGIONS = {"Інші країни"}


def _ensure_nmt_csv(data_dir: Path) -> Path:
    extracted = data_dir / "_extracted" / "Odata2025File.csv"
    if extracted.exists():
        return extracted
    archive = data_dir / "nmt" / "OpenDataNMT2025.7z"
    extracted.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["bsdtar", "-xf", str(archive), "-C", str(extracted.parent), "Odata2025File.csv"],
        check=True,
    )
    return extracted


def _parse_score(raw: str) -> float:
    return float(raw.replace(",", "."))


class NmtStep(Step):
    name = "nmt"

    def run(self, ctx: EtlContext) -> EtlTables:
        csv_path = _ensure_nmt_csv(ctx.data_dir)
        stats: dict[str, dict] = defaultdict(
            lambda: {
                "count": 0,
                "ukr": [],
                "math": [],
                "hist": [],
                "any_180": 0,
                "eng": 0,
                "electives": Counter(),
            }
        )

        with csv_path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                raw_reg = row["RegName"].strip()
                if raw_reg in _SKIP_REGIONS:
                    continue
                rid = normalize_region(raw_reg)
                st = stats[rid]
                st["count"] += 1

                has_180 = False
                for subj, status_col, ball_col in (
                    ("ukr", "UkrBlockStatus", "UkrBlockBall100"),
                    ("math", "MathBlockStatus", "MathBlockBall100"),
                    ("hist", "HistBlockStatus", "HistBlockBall100"),
                ):
                    if row[status_col] == "Зараховано":
                        score = _parse_score(row[ball_col])
                        st[subj].append(score)
                        if score >= 180.0:
                            has_180 = True

                for status_col, label in _ELECTIVES:
                    status = row[status_col]
                    if status and status != "null":
                        st["electives"][label] += 1
                        if label == "англійська мова":
                            st["eng"] += 1
                        if status == "Зараховано":
                            ball_col = status_col.replace("Status", "Ball100")
                            if _parse_score(row[ball_col]) >= 180.0:
                                has_180 = True

                if has_180:
                    st["any_180"] += 1

        region_metrics: list[RegionMetric] = []
        for rid in sorted(stats):
            st = stats[rid]
            cnt = st["count"]
            region_metrics.append(RegionMetric(rid, "nmt_participants", float(cnt), year=NMT_YEAR))

            reg = ctx.regions.get(rid)
            if reg and reg.population:
                per_1000 = round((cnt / reg.population) * 1000.0, 2)
                region_metrics.append(RegionMetric(rid, "nmt_participants_per_1000", per_1000, year=NMT_YEAR))

            for subj in ("ukr", "math", "hist"):
                scores = st[subj]
                if scores:
                    avg = round(sum(scores) / len(scores), 2)
                    share_180 = round(sum(1 for s in scores if s >= 180.0) / len(scores) * 100.0, 2)
                    region_metrics.append(RegionMetric(rid, f"nmt_avg_{subj}", avg, year=NMT_YEAR))
                    region_metrics.append(RegionMetric(rid, f"nmt_180_{subj}", share_180, year=NMT_YEAR))

            region_metrics.append(RegionMetric(rid, "nmt_any_180_share", round(st["any_180"] / cnt * 100.0, 2), year=NMT_YEAR))
            region_metrics.append(RegionMetric(rid, "nmt_eng_share", round(st["eng"] / cnt * 100.0, 2), year=NMT_YEAR))

            electives: Counter = st["electives"]
            if electives:
                top_all = electives.most_common(1)[0][0]
                region_metrics.append(RegionMetric(rid, "nmt_top_elective", None, value_text=top_all, year=NMT_YEAR))
                non_eng = [(k, v) for k, v in electives.most_common() if k != "англійська мова"]
                if non_eng:
                    region_metrics.append(RegionMetric(rid, "nmt_top_elective_non_eng", None, value_text=non_eng[0][0], year=NMT_YEAR))

        return EtlTables(metrics=list(NMT_METRICS), region_metrics=region_metrics)
