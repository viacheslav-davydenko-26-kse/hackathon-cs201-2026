"""Підбір підказок для раунду. Власник: Матвій (інтерфейс `HintPicker` — контракт, змінює Слава).

Хто використовує: app/game/solo.py, app/game/rooms.py (через app/deps.py).
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Iterable

from app.config import TOTAL_HINTS
from app.domain import Fact
from app.errors import RegionNotPlayable
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
      * `RegionNotFound` для невідомого id, `RegionNotPlayable` для playable=False.
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


class FactHintPicker(HintPicker):
    """Справжній підбір на таблиці facts. TODO(Матвій)."""

    def pick(self, region_id: str, n: int = TOTAL_HINTS, rng: random.Random | None = None) -> list[Hint]:
        self._require_playable(region_id)
        # 1. facts = self.repo.facts(region_id)
        # 2. жадібно: різні категорії, сортування за info, перевірка candidates(...) == {region_id}
        # 3. return to_hints(chosen)
        raise NotImplementedError("FactHintPicker.pick — Матвій")


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
