"""Мультиплеєр-кімнати. Чистий Python, без залежності від HTTP. Власник: Слава.

Фонового таймера НЕМА: усе, що залежить від часу (відкриті підказки, кінець раунду),
рахується з `started_at` при кожному виклику — див. `open_hint_count` / `next_hint_at`.
"""
from __future__ import annotations

import logging
import math
import random
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

from app.config import PUBLIC_URL, ROUND_SECONDS, TOTAL_HINTS, TOTAL_ROUNDS
from app.domain import Clock
from app.errors import (
    AlreadyGuessed, BadHostKey, InvalidName, InvalidState, NameTaken, PlayerNotFound, RegionNotPlayable,
    RoomNotFound, RoundFinished,
)
from app.game.card import CardBuilder
from app.game.hints import HintPicker
from app.game.picking import pick_round
from app.game.scoring import haversine, heat, points, speed_bonus
from app.qr import join_url, qr_svg
from app.repository import Repository
from app.schemas import (
    Card, Hint, JoinResponse, LeaderboardRow, Player, Reveal, RevealGuess, RoomCreated, RoomGuessResponse,
    RoomState, RoomStatus,
)

log = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # без 0/O/1/I
CODE_LENGTH = 4
MAX_NAME_LENGTH = 20
#: Кімната, якої не чіпали стільки секунд, видаляється при створенні нової.
ROOM_TTL_SECONDS = 6 * 3600


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
    guesses: dict[str, RoomGuess] = field(default_factory=dict)   # player_id → guess, у порядку прийняття
    points: dict[str, int] = field(default_factory=dict)          # заповнюється на reveal
    distances: dict[str, float] = field(default_factory=dict)     # player_id → км (неокруглені)
    revealed: bool = False
    card: Card | None = None


@dataclass
class Room:
    code: str
    host_key: str
    created_at: float
    status: RoomStatus = "lobby"
    players: dict[str, RoomPlayer] = field(default_factory=dict)  # порядок вставки = порядок приєднання
    rounds: list[RoomRound] = field(default_factory=list)
    used_regions: set[str] = field(default_factory=set)           # без повторів у межах кімнати
    touched_at: float = 0.0

    @property
    def current(self) -> RoomRound | None:
        return self.rounds[-1] if self.rounds else None


# ------------------------------------------------------------------ інтерфейс
class RoomManager(ABC):
    """Контракт (state machine і помилки — docs/contract.md → «Кімнати»):

    create_room(public_url=None)     → RoomCreated (status=lobby). Код: 4 символи [A-Z0-9] без 0/O/1/I.
                                       public_url — база для join_url/QR (None → значення з конфігу).
    join(code, name)                 → JoinResponse. Можна в lobby/round/reveal; finished → InvalidState.
                                       name обрізається (strip), 1–20 символів → інакше InvalidName;
                                       дубль імені (без регістру) → NameTaken.
    start(code, host_key)            → RoomState. lobby → round 1. Інакше InvalidState. Чужий ключ → BadHostKey.
    next(code, host_key)             → RoomState. round → reveal (дострокове завершення);
                                       reveal → round n+1, або finished після останнього.
    guess(code, player_id, region)   → RoomGuessResponse. Приймається, лише якщо status == round і now < ends_at.
                                       Порядок перевірок: RoomNotFound → PlayerNotFound → RegionNotFound →
                                       RegionNotPlayable → (lobby/finished: InvalidState) →
                                       (reveal або now >= ends_at: RoundFinished) → AlreadyGuessed.
                                       Відхилена відповідь стан не змінює.
    state(code, player_id=None)      → RoomState. Невідомий player_id → анонімний стан (me=None, my_guess=None), 200.

    Автопереходи (ліниво, на початку будь-якого виклику): round → reveal, коли now >= ends_at
    або всі гравці (усі, хто приєднався, — «відключених» не буває) відповіли.
    hint_index відповіді фіксується в момент прийняття: open_hint_count(started_at, at, ...) - 1.
    Бали на reveal: scoring.points(correct, d_km, hint_index) + (correct ? scoring.speed_bonus(ends_at - at,
    round_seconds) : 0); d_km неокруглена. Хто не відповів — 0.
    Порядок: leaderboard — score спадно, при рівності — порядок приєднання; reveal.guesses — порядок прийняття.
    Регіони в межах кімнати не повторюються (поки є невикористані); DataUnavailable від picker → інший регіон.
    card: якщо CardBuilder кинув будь-який виняток — reveal іде далі з card=None (виняток логується).
    """

    @abstractmethod
    def create_room(self, public_url: str | None = None) -> RoomCreated: ...

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
                 total_rounds: int = TOTAL_ROUNDS, public_url: str = PUBLIC_URL,
                 rng: random.Random | None = None):
        self.repo, self.picker, self.card_builder, self.clock = repo, picker, card_builder, clock
        self.round_seconds, self.total_rounds, self.public_url = round_seconds, total_rounds, public_url
        self.rng = rng or random.Random()
        self.rooms: dict[str, Room] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ API
    def create_room(self, public_url: str | None = None) -> RoomCreated:
        with self._lock:
            now = self.clock()
            self._evict(now)
            code = self._new_code()
            room = Room(code=code, host_key="hk_" + secrets.token_hex(8), created_at=now, touched_at=now)
            self.rooms[code] = room
            url = join_url(code, public_url or self.public_url)
            return RoomCreated(code=code, host_key=room.host_key, join_url=url, qr_svg=qr_svg(url))

    def join(self, code: str, name: str) -> JoinResponse:
        with self._lock:
            now = self.clock()
            room = self._room(code, now)
            if room.status == "finished":
                raise InvalidState("game is finished")
            name = " ".join(name.split())
            if not 1 <= len(name) <= MAX_NAME_LENGTH:
                raise InvalidName(f"name must be 1–{MAX_NAME_LENGTH} characters")
            if any(p.name.casefold() == name.casefold() for p in room.players.values()):
                raise NameTaken(f"name {name!r} is taken")
            pid = self._new_id("p_", room.players)
            room.players[pid] = RoomPlayer(id=pid, name=name, joined_at=now)
            return JoinResponse(player_id=pid)

    def start(self, code: str, host_key: str) -> RoomState:
        with self._lock:
            now = self.clock()
            room = self._room(code, now, host_key)
            if room.status != "lobby":
                raise InvalidState(f"cannot start: room is {room.status}")
            self._start_round(room, now)
            return self._state(room, now, None)

    def next(self, code: str, host_key: str) -> RoomState:
        with self._lock:
            now = self.clock()
            room = self._room(code, now, host_key)
            if room.status == "round":
                self._reveal(room)
            elif room.status == "reveal":
                if len(room.rounds) < self.total_rounds:
                    self._start_round(room, now)
                else:
                    room.status = "finished"
            else:
                raise InvalidState(f"cannot advance: room is {room.status}")
            return self._state(room, now, None)

    def guess(self, code: str, player_id: str, region_id: str) -> RoomGuessResponse:
        with self._lock:
            now = self.clock()
            room = self._room(code, now)
            if player_id not in room.players:
                raise PlayerNotFound(f"unknown player {player_id!r}")
            if not self.repo.region(region_id).playable:          # RegionNotFound
                raise RegionNotPlayable(f"{region_id} is not playable")
            if room.status in ("lobby", "finished"):
                raise InvalidState(f"cannot guess: room is {room.status}")
            rnd = room.current
            if room.status == "reveal" or now >= rnd.ends_at:
                raise RoundFinished("round is over")
            if player_id in rnd.guesses:
                raise AlreadyGuessed("you have already answered this round")
            hint_index = max(0, open_hint_count(rnd.started_at, now, self.round_seconds, len(rnd.hints)) - 1)
            rnd.guesses[player_id] = RoomGuess(player_id=player_id, region_id=region_id, at=now,
                                               hint_index=hint_index)
            self._advance(room, now)                               # усі відповіли → reveal
            return RoomGuessResponse(region_id=region_id)

    def state(self, code: str, player_id: str | None = None) -> RoomState:
        with self._lock:
            now = self.clock()
            room = self._room(code, now)
            return self._state(room, now, player_id)

    # ------------------------------------------------------------------ переходи
    def _room(self, code: str, now: float, host_key: str | None = None) -> Room:
        room = self.rooms.get(code.upper())
        if room is None:
            raise RoomNotFound(f"unknown room {code!r}")
        if host_key is not None and not secrets.compare_digest(host_key, room.host_key):
            raise BadHostKey("wrong host key")
        room.touched_at = now
        self._advance(room, now)
        return room

    def _advance(self, room: Room, now: float) -> None:
        """Лінивий автоперехід round → reveal (дедлайн або всі відповіли)."""
        rnd = room.current
        if room.status != "round" or rnd is None:
            return
        everyone = bool(room.players) and all(pid in rnd.guesses for pid in room.players)
        if now >= rnd.ends_at or everyone:
            self._reveal(room)

    def _start_round(self, room: Room, now: float) -> None:
        region_id, hints = pick_round(self.picker, self.rng, exclude=room.used_regions)
        room.used_regions.add(region_id)
        room.rounds.append(RoomRound(no=len(room.rounds) + 1, region_id=region_id, hints=hints,
                                     started_at=now, ends_at=now + self.round_seconds))
        room.status = "round"

    def _reveal(self, room: Room) -> None:
        rnd = room.current
        answer = self.repo.region(rnd.region_id)
        for pid, g in rnd.guesses.items():
            correct = g.region_id == rnd.region_id
            guessed = self.repo.region(g.region_id)
            d = 0.0 if correct else haversine(guessed.lat, guessed.lon, answer.lat, answer.lon)
            pts = points(correct, d, g.hint_index)
            if correct:
                pts += speed_bonus(rnd.ends_at - g.at, self.round_seconds)
            rnd.distances[pid], rnd.points[pid] = d, pts
            room.players[pid].score += pts
        rnd.card = self._card(rnd.region_id)
        rnd.revealed = True
        room.status = "reveal"

    def _card(self, region_id: str) -> Card | None:
        if self.card_builder is None:
            return None
        try:
            return self.card_builder.build(region_id)
        except NotImplementedError as e:
            log.warning("card for %s: %s; reveal continues with card=None", region_id, e)
            return None
        except Exception:  # контракт D2: reveal не падає через картку
            log.exception("card for %s failed; reveal continues with card=None", region_id)
            return None

    # ------------------------------------------------------------------ стан
    def _state(self, room: Room, now: float, player_id: str | None) -> RoomState:
        rnd = room.current
        status = room.status
        last_revealed = next((r for r in reversed(room.rounds) if r.revealed), None)

        hints: list[Hint] = []
        started_at = ends_at = next_at = None
        if rnd is not None:
            if status == "round":
                hints = rnd.hints[: open_hint_count(rnd.started_at, now, self.round_seconds, len(rnd.hints))]
                next_at = next_hint_at(rnd.started_at, now, self.round_seconds, len(rnd.hints))
            else:
                hints = list(rnd.hints)
            if status in ("round", "reveal"):
                started_at, ends_at = rnd.started_at, rnd.ends_at

        players = [Player(id=p.id, name=p.name, score=p.score) for p in room.players.values()]
        me = next((p for p in players if p.id == player_id), None)
        my_guess = None
        if me is not None and rnd is not None and status in ("round", "reveal") and player_id in rnd.guesses:
            my_guess = rnd.guesses[player_id].region_id

        reveal = None
        if status in ("reveal", "finished") and rnd is not None and rnd.revealed:
            reveal = Reveal(
                answer_region_id=rnd.region_id,
                guesses=[RevealGuess(player_id=pid, name=room.players[pid].name, region_id=g.region_id,
                                     distance_km=round(rnd.distances[pid], 1), heat=heat(rnd.distances[pid]),
                                     points=rnd.points[pid])
                         for pid, g in rnd.guesses.items()],
                distribution=dict(Counter(g.region_id for g in rnd.guesses.values())),
                card=rnd.card,
            )

        deltas = last_revealed.points if last_revealed else {}
        board = sorted(room.players.values(), key=lambda p: -p.score)     # stable → при рівності порядок join
        leaderboard = [LeaderboardRow(player_id=p.id, name=p.name, score=p.score, delta=deltas.get(p.id, 0))
                       for p in board]

        return RoomState(
            code=room.code, status=status, server_now=now, players=players,
            round_no=len(room.rounds), total_rounds=self.total_rounds,
            started_at=started_at, ends_at=ends_at, next_hint_at=next_at, hints=hints,
            answered=len(rnd.guesses) if rnd is not None and status != "lobby" else 0,
            total=len(room.players), me=me, my_guess=my_guess, reveal=reveal, leaderboard=leaderboard,
        )

    # ------------------------------------------------------------------ helpers
    def _new_code(self) -> str:
        for _ in range(1000):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                return code
        raise RuntimeError("no free room codes")

    @staticmethod
    def _new_id(prefix: str, taken) -> str:
        while (pid := prefix + secrets.token_hex(4)) in taken:
            pass
        return pid

    def _evict(self, now: float) -> None:
        for code in [c for c, r in self.rooms.items() if now - r.touched_at > ROOM_TTL_SECONDS]:
            del self.rooms[code]
