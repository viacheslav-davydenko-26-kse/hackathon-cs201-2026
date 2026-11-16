"""Підбір підказок для раунду. Власник: Матвій (інтерфейс `HintPicker` — контракт, змінює Слава).

Хто використовує: app/game/solo.py, app/game/rooms.py (через app/deps.py).
Алгоритм — `pick_hints_from_list()` (чиста функція на dict-ах); `FactHintPicker` — адаптер до інтерфейсу.
"""
from __future__ import annotations

import itertools
import json
import random
from collections import defaultdict
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.config import TOTAL_HINTS
from app.domain import Fact
from app.errors import DataUnavailable, RegionNotPlayable
from app.repository import Repository
from app.schemas import Hint


class HintPicker(ABC):
    """Повертає підказки для загаданого регіону.

    Контракт `pick()`:
      * рівно `n` підказок, `Hint.index` = 0..n-1;
      * порядок: від найважчої (найменший `Fact.info`) до найлегшої;
      * категорії якомога різноманітніші (не дві підряд з однієї);
      * текст НЕ містить назви регіону чи прикметників від неї;
      * для однакового `rng` (seed) результат однаковий;
      * `RegionNotFound` для невідомого id, `RegionNotPlayable` для playable=False;
      * `DataUnavailable`, якщо для регіону неможливо зібрати коректний раунд — тоді сервіс
        (solo/rooms) пробує інший регіон, а 503 віддає, лише коли не підходить жоден.
    Реалізація на фактах додатково гарантує: перетин `consistent` усіх n фактів == {region_id}.
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    @abstractmethod
    def pick(self, region_id: str, n: int = TOTAL_HINTS, rng: random.Random | None = None) -> list[Hint]: ...

    def random_region(self, rng: random.Random | None = None) -> str:
        """Випадковий ігровий регіон. Можна перевизначити (напр., пропускати «погані» регіони)."""
        return (rng or random).choice([r.id for r in self.repo.playable_regions()])

    def _require_playable(self, region_id: str) -> None:
        if not self.repo.region(region_id).playable:
            raise RegionNotPlayable(region_id)


def candidates(facts: Iterable[Fact]) -> set[str] | None:
    """Перетин `consistent` — регіони, які ще підходять під усі факти. None для порожнього входу."""
    result: set[str] | None = None
    for f in facts:
        result = set(f.consistent) if result is None else result & f.consistent
    return result


def to_hints(facts: list[Fact]) -> list[Hint]:
    """Факти (вже у правильному порядку) → Hint з index 0..n-1."""
    return [Hint(index=i, text=f.riddle_uk or f.text_uk, metric_id=f.metric_id, category=f.category)
            for i, f in enumerate(facts)]


# ------------------------------------------------------------------ алгоритм (Матвій)
#: «Конкретний» факт підходить щонайбільше стільком регіонам. Ширші («в межах ±5% від середнього»
#: для половини країни) майже нічого не кажуть про загадану область — беремо їх лише як фолбек.
SPECIFIC_MAX_CONSISTENT = 12
PICK_ATTEMPTS = 300


def _adjacent_repeats(seq: list[dict]) -> int:
    return sum(a["category"] == b["category"] for a, b in zip(seq, seq[1:]))


def order_hints(chosen: list[dict]) -> list[dict]:
    """Порядок показу: спершу без сусідніх однакових категорій (якщо це можливо для набору),
    далі — якомога ближче до зростання info (від найважчої до найлегшої)."""
    def inversions(seq):
        return sum(a["info"] > b["info"] for i, a in enumerate(seq) for b in seq[i + 1:])
    base = sorted(chosen, key=lambda f: f["info"])
    return list(min(itertools.permutations(base), key=lambda p: (_adjacent_repeats(list(p)), inversions(p))))


def _try_build(region_id: str, pool: list[dict], n: int, rng: random.Random,
               strict: bool = True) -> list[dict] | None:
    """Одна спроба: n фактів різних метрик, кожен строго звужує кандидатів, лише останній дає {region_id}.
    Після i-ї підказки лишається ≥ n-i кандидатів, щоб наступним було що звужувати.
    strict=False — фолбек: дозволяє однозначність раніше і «порожні» підказки після неї."""
    chosen: list[dict] = []
    cand: set[str] | None = None
    cat_count: dict[str, int] = defaultdict(int)
    for step in range(n):
        last = step == n - 1
        options = []
        for f in pool:
            if any(f["metric_id"] == c["metric_id"] for c in chosen):
                continue
            new = f["_set"] if cand is None else cand & f["_set"]
            if strict:
                if cand is not None and len(new) == len(cand):
                    continue                               # нічого не додає
                if last != (new == {region_id}) or (not last and len(new) < n - step):
                    continue                               # однозначність — лише на останній
            elif last and new != {region_id}:
                continue
            options.append((f, new))
        if not options:
            return None
        # Різноманіття: найменш використана категорія; серед неї — важчі (менше info) з шумом.
        least = min(cat_count[f["category"]] for f, _ in options)
        options = [o for o in options if cat_count[o[0]["category"]] == least]
        options.sort(key=lambda o: o[0]["info"] + rng.random() * 1.5)
        f, cand = options[0]
        chosen.append(f)
        cat_count[f["category"]] += 1
    return chosen


def pick_hints_from_list(region_id: str, region_facts: list[dict], n: int = 5, seed: int | None = None) -> list[dict]:
    """n підказок, перетин `consistent` яких == {region_id}; [] якщо зібрати не вдалося.

    1. Беремо лише конкретні факти (|consistent| ≤ SPECIFIC_MAX_CONSISTENT), а якщо з ними не виходить —
       усі. Кожна підказка звужує коло кандидатів; однозначно — лише після останньої.
    2. Набір з найменшою кількістю сусідніх повторів категорії (в ідеалі 0) і більшим розмаїттям.
    3. Порядок — `order_hints`: без повторів категорій підряд, далі від важчої до легшої.
    """
    rng = random.Random(seed)
    facts = [dict(f, _set=set(json.loads(f["consistent"]))) for f in region_facts if f["region_id"] == region_id]
    facts = [f for f in facts if region_id in f["_set"]]
    specific = [f for f in facts if len(f["_set"]) <= SPECIFIC_MAX_CONSISTENT]

    best, best_key = None, None
    for pool, strict in ((specific, True), (facts, True), (facts, False)):
        for _ in range(PICK_ATTEMPTS):
            chosen = _try_build(region_id, pool, n, rng, strict)
            if chosen is None:
                continue
            ordered = order_hints(chosen)
            key = (_adjacent_repeats(ordered), -len({f["category"] for f in ordered}))
            if best_key is None or key < best_key:
                best, best_key = ordered, key
            if key[0] == 0 and -key[1] >= min(3, len({f["category"] for f in pool})):
                break
        if best is not None:
            break
    if best is None:
        return []
    return [{"index": i, "text": f["text_uk"], "metric_id": f["metric_id"], "category": f["category"]}
            for i, f in enumerate(best)]


def pick_hints(conn: sqlite3.Connection, region_id: str, n: int = 5, seed: int | None = None) -> list[dict]:
    """Прямо з SQLite (для скриптів/дебагу). Сервер ходить через FactHintPicker + Repository."""
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


def fact_to_dict(f: Fact) -> dict:
    """Fact (dataclass) → dict у форматі, який чекає pick_hints_from_list."""
    return {"region_id": f.region_id, "metric_id": f.metric_id, "kind": f.kind, "text_uk": f.riddle_uk or f.text_uk,
            "consistent": json.dumps(sorted(f.consistent)), "info": f.info, "category": f.category}


# ------------------------------------------------------------------ реалізації інтерфейсу
class FactHintPicker(HintPicker):
    """Справжній підбір на таблиці facts (алгоритм — pick_hints_from_list)."""

    def pick(self, region_id: str, n: int = TOTAL_HINTS, rng: random.Random | None = None) -> list[Hint]:
        self._require_playable(region_id)
        seed = (rng or random.Random()).randrange(2**32)
        facts = [fact_to_dict(f) for f in self.repo.facts(region_id)]
        hints = pick_hints_from_list(region_id, facts, n=n, seed=seed)
        by_key = {(f["metric_id"], f["text_uk"]): set(json.loads(f["consistent"])) for f in facts}
        cand = set.intersection(*(by_key[(h["metric_id"], h["text"])] for h in hints)) if hints else set()
        if len(hints) != n or cand != {region_id}:
            raise DataUnavailable(f"cannot build a unique {n}-hint round for {region_id!r}")
        return [Hint(**h) for h in hints]


class RandomHintPicker(HintPicker):
    """ТИМЧАСОВИЙ: n випадкових сирих значень метрик. Унікальність відповіді НЕ гарантує."""

    def pick(self, region_id: str, n: int = TOTAL_HINTS, rng: random.Random | None = None) -> list[Hint]:
        self._require_playable(region_id)
        rng = rng or random.Random()
        metrics = {m.id: m for m in self.repo.metrics()}
        rows = [rm for rm in self.repo.region_metrics(region_id)
                if rm.metric_id in metrics and (rm.value is not None or rm.value_text)]
        chosen = rng.sample(rows, min(n, len(rows)))
        hints = []
        for i, rm in enumerate(chosen):
            m = metrics[rm.metric_id]
            value = rm.value_text if m.kind == "categorical" else f"{rm.value:g} {m.unit or ''}".strip()
            hints.append(Hint(index=i, text=f"{m.title_uk}: {value}", metric_id=m.id, category=m.category))
        return hints
