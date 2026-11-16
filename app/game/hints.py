import json
import random
import sqlite3


def pick_hints_from_list(region_id: str, region_facts: list[dict], n: int = 5, seed: int | None = None) -> list[dict]:
    rng = random.Random(seed)
    # Додаємо легкий шум при однакових info, щоб раунди не повторювалися
    shuffled = list(region_facts)
    rng.shuffle(shuffled)
    sorted_facts = sorted(shuffled, key=lambda f: f["info"])

    chosen = []
    used_metrics = set()
    used_categories = set()
    candidates = None

    # Крок 1: беремо n-1 підказок із різних категорій, притримуючи 'raw' на кінець
    for f in sorted_facts:
        if len(chosen) >= n - 1:
            break
        if f["metric_id"] in used_metrics:
            continue
        if f["kind"] == "raw" and len(chosen) < n - 2:
            continue
        if f["category"] not in used_categories or len(used_categories) >= 3:
            chosen.append(f)
            used_metrics.add(f["metric_id"])
            used_categories.add(f["category"])
            c_set = set(json.loads(f["consistent"]))
            candidates = c_set if candidates is None else (candidates & c_set)

    # Крок 2: 5-та підказка гарантовано звужує перетин до {region_id}
    for f in sorted_facts:
        if f["metric_id"] in used_metrics:
            continue
        c_set = set(json.loads(f["consistent"]))
        new_cand = c_set if candidates is None else (candidates & c_set)
        if new_cand == {region_id}:
            chosen.append(f)
            used_metrics.add(f["metric_id"])
            candidates = new_cand
            break

    # Фолбек, якщо не вистачило підказок
    for f in sorted_facts:
        if len(chosen) >= n:
            break
        if f["metric_id"] not in used_metrics:
            chosen.append(f)
            used_metrics.add(f["metric_id"])

    chosen.sort(key=lambda f: f["info"])

    return [
        {
            "index": idx,
            "text": f["text_uk"],
            "metric_id": f["metric_id"],
            "category": f["category"],
        }
        for idx, f in enumerate(chosen)
    ]


def pick_hints(conn: sqlite3.Connection, region_id: str, n: int = 5, seed: int | None = None) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT f.region_id, f.metric_id, f.kind, f.text_uk, f.consistent, f.info, m.category
        FROM facts f
        JOIN metrics m ON m.id = f.metric_id
        WHERE f.region_id = ?
        """,
        (region_id,),
    ).fetchall()
    return pick_hints_from_list(region_id, [dict(r) for r in rows], n=n, seed=seed)
