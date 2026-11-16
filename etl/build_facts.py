import csv
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

TOTAL_PLAYABLE = 25


def calc_info(consistent: list[str]) -> float:
    return round(math.log2(TOTAL_PLAYABLE / max(1, len(consistent))), 3)


def load_catalog(metrics_csv: str | Path) -> dict[str, dict]:
    catalog = {}
    with open(metrics_csv, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            catalog[row["id"]] = row
    return catalog


def load_region_metrics(rm_csv: str | Path) -> dict[str, list[dict]]:
    by_metric = defaultdict(list)
    with open(rm_csv, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["value"] = float(row["value"]) if row["value"] != "" else None
            row["year"] = int(float(row["year"])) if row["year"] != "" else None
            row["rank"] = int(float(row["rank"])) if row["rank"] != "" else None
            row["n_ranked"] = int(float(row["n_ranked"])) if row["n_ranked"] != "" else None
            by_metric[row["metric_id"]].append(row)
    return by_metric


def build_all_facts(metrics_csv: str | Path, rm_csv: str | Path) -> list[dict]:
    catalog = load_catalog(metrics_csv)
    by_metric = load_region_metrics(rm_csv)
    facts: list[dict] = []

    for metric_id, rows in by_metric.items():
        meta = catalog.get(metric_id)
        if not meta:
            continue
        title = meta["title_uk"]
        unit = meta["unit"]
        kind = meta["kind"]
        category = meta["category"]

        # 1. Категоріальні метрики (nmt_top_elective, cars_top_brand тощо)
        if kind == "categorical":
            by_text = defaultdict(list)
            for r in rows:
                if r["value_text"]:
                    by_text[r["value_text"]].append(r["region_id"])

            for r in rows:
                val_txt = r["value_text"]
                if not val_txt:
                    continue
                cons = sorted(by_text[val_txt])
                facts.append({
                    "region_id": r["region_id"],
                    "metric_id": metric_id,
                    "category": category,
                    "kind": "categorical",
                    "text_uk": f"{title} — {val_txt}",
                    "consistent": json.dumps(cons, ensure_ascii=False),
                    "info": calc_info(cons),
                    "riddle_uk": None,
                })

        # 2. Числові метрики (rank, relative, raw)
        elif kind == "numeric":
            valid = [r for r in rows if r["value"] is not None]
            if not valid:
                continue

            avg_val = sum(r["value"] for r in valid) / len(valid)
            top3 = sorted([r["region_id"] for r in valid if r["rank"] and r["rank"] <= 3])
            bot3 = sorted([r["region_id"] for r in valid if r["rank"] and r["n_ranked"] and r["rank"] > r["n_ranked"] - 3])

            buckets = defaultdict(list)
            reg_bucket = {}
            for r in valid:
                diff_pct = ((r["value"] - avg_val) / avg_val) * 100.0 if avg_val != 0 else 0.0
                b = int(round(diff_pct / 10.0) * 10)
                buckets[b].append(r["region_id"])
                reg_bucket[r["region_id"]] = b

            for r in valid:
                reg = r["region_id"]
                val = r["value"]
                rank = r["rank"]
                n_ranked = r["n_ranked"]

                # A. Rank
                rank1_regions = sorted([r["region_id"] for r in valid if r["rank"] == 1])

                # Усередині циклу по регіонах:
                if rank == 1:
                    if len(rank1_regions) == 1:
                        r1_text = f"1-ше місце в Україні: {title}"
                    else:
                        r1_text = f"Ділить 1-ше місце в Україні: {title}"
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": r1_text,
                        "consistent": json.dumps(rank1_regions), "info": calc_info(rank1_regions), "riddle_uk": None,
                    })
                elif rank and rank <= 3:
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": f"У топ-3 областей за показником «{title}»",
                        "consistent": json.dumps(top3), "info": calc_info(top3), "riddle_uk": None,
                    })
                elif rank and n_ranked and rank > n_ranked - 3:
                    facts.append({
                        "region_id": reg, "metric_id": metric_id, "category": category,
                        "kind": "rank", "text_uk": f"В останніх 3 областях за показником «{title}»",
                        "consistent": json.dumps(bot3), "info": calc_info(bot3), "riddle_uk": None,
                    })

                # B. Relative (бакети ±10%)
                b = reg_bucket[reg]
                cons_rel = sorted(buckets[b])
                if b == 0:
                    rel_txt = f"{title}: приблизно на рівні середнього по Україні (±10%)"
                elif b > 0:
                    rel_txt = f"{title}: приблизно на {abs(b)}% вище за середнє по Україні"
                else:
                    rel_txt = f"{title}: приблизно на {abs(b)}% нижче за середнє по Україні"

                facts.append({
                    "region_id": reg, "metric_id": metric_id, "category": category,
                    "kind": "relative", "text_uk": rel_txt,
                    "consistent": json.dumps(cons_rel), "info": calc_info(cons_rel), "riddle_uk": None,
                })

                # C. Raw (точне значення)
                cons_raw = [reg]
                val_str = f"{val:g}" if isinstance(val, int) or val.is_integer() else f"{val:.2f}"
                facts.append({
                    "region_id": reg, "metric_id": metric_id, "category": category,
                    "kind": "raw", "text_uk": f"{title}: {val_str} {unit}".strip(),
                    "consistent": json.dumps(cons_raw), "info": calc_info(cons_raw), "riddle_uk": None,
                })

    return facts


def save_facts_to_sqlite(db_path: str | Path, facts: list[dict]) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM facts")
    cur.executemany(
        """
        INSERT INTO facts (region_id, metric_id, kind, text_uk, consistent, info, riddle_uk)
        VALUES (:region_id, :metric_id, :kind, :text_uk, :consistent, :info, :riddle_uk)
        """,
        facts,
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    all_facts = build_all_facts("data/parsed/metrics.csv", "data/parsed/region_metrics.csv")
    print(f"Згенеровано фактів: {len(all_facts)}")
