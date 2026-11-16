"""Соло-раунди (стан у пам'яті процесу). Власник: Слава."""
from __future__ import annotations

import random
import secrets
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import SOLO_MAX_ATTEMPTS
from app.domain import Clock
from app.errors import AlreadyGuessed, DataUnavailable, NoMoreHints, RegionNotPlayable, RoundFinished, RoundNotFound
from app.game.hints import HintPicker
from app.game.picking import pick_round
from app.game.scoring import haversine, heat, points
from app.repository import Repository
from app.schemas import Hint, HintsResponse, SoloGuessResponse, SoloRound

#: Соло-раунд, якого не чіпали стільки секунд, видаляється (захист від росту пам'яті).
ROUND_TTL_SECONDS = 2 * 3600


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
    touched_at: float = 0.0

    @property
    def open_hints(self) -> list[Hint]:
        return self.hints[: self.opened]


class SoloService(ABC):
    """Контракт (див. також docs/contract.md → «Соло» і §9 S1–S5):

    start_round()      → SoloRound з 1 відкритою підказкою. Регіон, для якого picker кинув
                         DataUnavailable, пропускається; 503 — лише якщо не підходить жоден.
    reveal_hint(id)    → HintsResponse з УСІМА відкритими. Помилки: RoundNotFound, RoundFinished, NoMoreHints.
    guess(id, region)  → SoloGuessResponse. Помилки (спробу НЕ витрачають, стан не змінюють), у такому порядку:
                         RoundNotFound, RoundFinished, RegionNotFound, RegionNotPlayable,
                         AlreadyGuessed (цей регіон уже називали в раунді).
    Бали: app.game.scoring.points(correct, d_km, hint_index=opened-1, attempt=n), d_km — НЕокруглена.
    total_points = сума points усіх спроб (неправильні з частковими балами теж).
    Відповідь: distance_km округлено до 0.1 (лише для показу); heat — з неокругленої відстані.
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
                 max_attempts: int = SOLO_MAX_ATTEMPTS, rng: random.Random | None = None):
        self.repo, self.picker, self.clock, self.max_attempts = repo, picker, clock, max_attempts
        self.rng = rng or random.Random()
        self.rounds: dict[str, SoloRoundState] = {}
        self._lock = threading.Lock()

    def start_round(self, rng: random.Random | None = None) -> SoloRound:
        region_id, hints = pick_round(self.picker, rng or self.rng)
        now = self.clock()
        with self._lock:
            self._evict(now)
            rid = self._new_id()
            st = SoloRoundState(id=rid, region_id=region_id, hints=hints, created_at=now, touched_at=now)
            self.rounds[rid] = st
            return SoloRound(round_id=rid, total_hints=len(hints), max_attempts=self.max_attempts,
                             hints=st.open_hints)

    def reveal_hint(self, round_id: str) -> HintsResponse:
        with self._lock:
            st = self._get(round_id)
            if st.finished:
                raise RoundFinished(f"round {round_id} is finished")
            if st.opened >= len(st.hints):
                raise NoMoreHints(f"all {len(st.hints)} hints are already open")
            st.opened += 1
            return HintsResponse(hints=st.open_hints)

    def guess(self, round_id: str, region_id: str) -> SoloGuessResponse:
        with self._lock:
            st = self._get(round_id)
            if st.finished:
                raise RoundFinished(f"round {round_id} is finished")
            guessed = self.repo.region(region_id)               # RegionNotFound
            if not guessed.playable:
                raise RegionNotPlayable(f"{region_id} is not playable")
            if region_id in st.guesses:
                raise AlreadyGuessed(f"{region_id} was already guessed in this round")

            answer = self.repo.region(st.region_id)
            correct = region_id == st.region_id
            distance = 0.0 if correct else _distance(guessed, answer)
            attempt = len(st.guesses) + 1
            pts = points(correct, distance, hint_index=st.opened - 1, attempt=attempt)

            st.guesses.append(region_id)
            st.total_points += pts
            st.correct = correct
            st.finished = correct or attempt >= self.max_attempts
            return SoloGuessResponse(
                correct=correct, attempt=attempt, attempts_left=self.max_attempts - attempt,
                finished=st.finished, distance_km=round(distance, 1), heat=heat(distance), points=pts,
                total_points=st.total_points, answer_region_id=st.region_id if st.finished else None,
            )

    # ---- helpers
    def _get(self, round_id: str) -> SoloRoundState:
        st = self.rounds.get(round_id)
        if st is None:
            raise RoundNotFound(f"unknown round {round_id!r}")
        st.touched_at = self.clock()
        return st

    def _new_id(self) -> str:
        while (rid := "r_" + secrets.token_hex(6)) in self.rounds:
            pass
        return rid

    def _evict(self, now: float) -> None:
        for rid in [rid for rid, st in self.rounds.items() if now - st.touched_at > ROUND_TTL_SECONDS]:
            del self.rounds[rid]


def _distance(a, b) -> float:
    if None in (a.lat, a.lon, b.lat, b.lon):
        raise DataUnavailable(f"no centroid for {a.id if a.lat is None else b.id}")
    return haversine(a.lat, a.lon, b.lat, b.lon)
