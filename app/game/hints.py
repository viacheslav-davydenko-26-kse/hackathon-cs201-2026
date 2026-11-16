"""Підбір підказок для раунду. Власник: Матвій (інтерфейс `HintPicker` — контракт, змінює Слава).

Хто використовує: app/game/solo.py, app/game/rooms.py (через app/deps.py).
Алгоритм — `pick_hints_from_list()` (чиста функція на dict-ах); `FactHintPicker` — адаптер до інтерфейсу.
"""
from __future__ import annotations

import json
import random
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
