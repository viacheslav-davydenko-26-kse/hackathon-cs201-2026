"""Соло-раунди (стан у пам'яті процесу). Власник: Слава."""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import SOLO_MAX_ATTEMPTS
from app.domain import Clock
from app.game.hints import HintPicker
from app.repository import Repository
from app.schemas import Hint, HintsResponse, SoloGuessResponse, SoloRound


@dataclass
class SoloRoundState:
    id: str
    region_id: str
    hints: list[Hint]                 # усі 5, відкриті — перші `opened`
    created_at: float
    opened: int = 1
    guesses: list[str] = field(default_factory=list)
    total_points: int = 0
    finished: bool = False
    correct: bool = False

    @property
    def open_hints(self) -> list[Hint]:
        return self.hints[: self.opened]


class SoloService(ABC):
    """Контракт (див. також docs/contract.md → «Соло»):

    start_round()      → SoloRound з 1 відкритою підказкою.
    reveal_hint(id)    → HintsResponse з УСІМА відкритими. Помилки: RoundNotFound, RoundFinished, NoMoreHints.
    guess(id, region)  → SoloGuessResponse. Помилки: RoundNotFound, RoundFinished, RegionNotFound,
                         RegionNotPlayable. Повторна відповідь тим самим регіоном — теж спроба.
    Бали: app.game.scoring.points(correct, d_km, hint_index=opened-1, attempt=n).
    Раунд finished, коли correct або attempts == SOLO_MAX_ATTEMPTS; тоді answer_region_id заповнено.
    """

    @abstractmethod
    def start_round(self, rng: random.Random | None = None) -> SoloRound: ...

    @abstractmethod
    def reveal_hint(self, round_id: str) -> HintsResponse: ...

    @abstractmethod
    def guess(self, round_id: str, region_id: str) -> SoloGuessResponse: ...


class InMemorySoloService(SoloService):
    def __init__(self, repo: Repository, picker: HintPicker, clock: Clock = time.time,
                 max_attempts: int = SOLO_MAX_ATTEMPTS):
        self.repo, self.picker, self.clock, self.max_attempts = repo, picker, clock, max_attempts
        self.rounds: dict[str, SoloRoundState] = {}

    def start_round(self, rng: random.Random | None = None) -> SoloRound:
        raise NotImplementedError("InMemorySoloService.start_round — Слава")

    def reveal_hint(self, round_id: str) -> HintsResponse:
        raise NotImplementedError("InMemorySoloService.reveal_hint — Слава")

    def guess(self, round_id: str, region_id: str) -> SoloGuessResponse:
        raise NotImplementedError("InMemorySoloService.guess — Слава")
