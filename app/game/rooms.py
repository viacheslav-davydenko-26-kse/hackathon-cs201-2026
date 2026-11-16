"""Мультиплеєр-кімнати. Чистий Python, без залежності від HTTP. Власник: Слава.

Фонового таймера НЕМА: усе, що залежить від часу (відкриті підказки, кінець раунду),
рахується з `started_at` при кожному виклику — див. `open_hint_count` / `next_hint_at`.
"""
from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import PUBLIC_URL, ROUND_SECONDS, TOTAL_HINTS, TOTAL_ROUNDS
from app.domain import Clock
from app.game.card import CardBuilder
from app.game.hints import HintPicker
from app.repository import Repository
from app.schemas import Hint, JoinResponse, RoomCreated, RoomGuessResponse, RoomState, RoomStatus


# ------------------------------------------------------------------ таймінг (контракт)
def open_hint_count(started_at: float, now: float, round_seconds: float, total_hints: int = TOTAL_HINTS) -> int:
    """Підказка i (0-based) відкривається в started_at + i * round_seconds / total_hints."""
    if now < started_at:
        return 0
    step = round_seconds / total_hints
    return min(total_hints, math.floor((now - started_at) / step) + 1)


def next_hint_at(started_at: float, now: float, round_seconds: float, total_hints: int = TOTAL_HINTS) -> float | None:
    opened = open_hint_count(started_at, now, round_seconds, total_hints)
    return None if opened >= total_hints else started_at + opened * round_seconds / total_hints


# ------------------------------------------------------------------ стан
@dataclass
class RoomPlayer:
    id: str
    name: str
    score: int = 0
    joined_at: float = 0.0


@dataclass
class RoomGuess:
    player_id: str
    region_id: str
    at: float
    hint_index: int                  # остання відкрита підказка в момент відповіді


@dataclass
class RoomRound:
    no: int                          # 1-based
    region_id: str
    hints: list[Hint]                # усі 5
    started_at: float
    ends_at: float
    guesses: dict[str, RoomGuess] = field(default_factory=dict)   # player_id → guess
    points: dict[str, int] = field(default_factory=dict)          # заповнюється на reveal


@dataclass
class Room:
    code: str
    host_key: str
    created_at: float
    status: RoomStatus = "lobby"
    players: dict[str, RoomPlayer] = field(default_factory=dict)  # порядок вставки = порядок приєднання
    rounds: list[RoomRound] = field(default_factory=list)
    used_regions: set[str] = field(default_factory=set)           # без повторів у межах кімнати


# ------------------------------------------------------------------ інтерфейс
class RoomManager(ABC):
    """Контракт (state machine і помилки — docs/contract.md → «Кімнати»):

    create_room()                    → RoomCreated (status=lobby). Код: 4 символи [A-Z0-9] без 0/O/1/I.
    join(code, name)                 → JoinResponse. Можна в lobby/round/reveal; finished → InvalidState.
                                       name обрізається (strip), 1–20 символів → інакше InvalidName;
                                       дубль імені (без регістру) → NameTaken.
    start(code, host_key)            → RoomState. lobby → round 1. Інакше InvalidState. Чужий ключ → BadHostKey.
    next(code, host_key)             → RoomState. round → reveal (дострокове завершення);
                                       reveal → round n+1, або finished після останнього.
    guess(code, player_id, region)   → RoomGuessResponse. Лише в round; друга відповідь → AlreadyGuessed.
    state(code, player_id=None)      → RoomState. Невідомий player_id ігнорується (me=None).

    Автопереходи (ліниво, у будь-якому виклику): round → reveal, коли now >= ends_at або всі гравці відповіли.
    Бали на reveal: scoring.points(correct, d_km, hint_index) + scoring.speed_bonus(ends_at - at, round_seconds)
    (бонус швидкості лише за правильну відповідь). Хто не відповів — 0.
    """

    @abstractmethod
    def create_room(self) -> RoomCreated: ...

    @abstractmethod
    def join(self, code: str, name: str) -> JoinResponse: ...

    @abstractmethod
    def start(self, code: str, host_key: str) -> RoomState: ...

    @abstractmethod
    def next(self, code: str, host_key: str) -> RoomState: ...

    @abstractmethod
    def guess(self, code: str, player_id: str, region_id: str) -> RoomGuessResponse: ...

    @abstractmethod
    def state(self, code: str, player_id: str | None = None) -> RoomState: ...


class InMemoryRoomManager(RoomManager):
    def __init__(self, repo: Repository, picker: HintPicker, card_builder: CardBuilder | None = None,
                 clock: Clock = time.time, round_seconds: int = ROUND_SECONDS,
                 total_rounds: int = TOTAL_ROUNDS, public_url: str = PUBLIC_URL):
        self.repo, self.picker, self.card_builder, self.clock = repo, picker, card_builder, clock
        self.round_seconds, self.total_rounds, self.public_url = round_seconds, total_rounds, public_url
        self.rooms: dict[str, Room] = {}

    def create_room(self) -> RoomCreated:
        raise NotImplementedError("InMemoryRoomManager.create_room — Слава")

    def join(self, code: str, name: str) -> JoinResponse:
        raise NotImplementedError("InMemoryRoomManager.join — Слава")

    def start(self, code: str, host_key: str) -> RoomState:
        raise NotImplementedError("InMemoryRoomManager.start — Слава")

    def next(self, code: str, host_key: str) -> RoomState:
        raise NotImplementedError("InMemoryRoomManager.next — Слава")

    def guess(self, code: str, player_id: str, region_id: str) -> RoomGuessResponse:
        raise NotImplementedError("InMemoryRoomManager.guess — Слава")

    def state(self, code: str, player_id: str | None = None) -> RoomState:
        raise NotImplementedError("InMemoryRoomManager.state — Слава")
