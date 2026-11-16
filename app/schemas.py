"""Pydantic-моделі = API-контракт (див. docs/contract.md). Змінює лише Слава."""
from typing import Literal

from pydantic import BaseModel

Heat = Literal["hot", "warm", "cool", "cold"]
RoomStatus = Literal["lobby", "round", "reveal", "finished"]


class Region(BaseModel):
    id: str
    name_uk: str
    short_uk: str
    playable: bool
    lat: float | None
    lon: float | None


class Hint(BaseModel):
    index: int
    text: str
    metric_id: str
    category: str


# ---- Solo ----
class SoloRound(BaseModel):
    round_id: str
    total_hints: int = 5
    hints: list[Hint]


class HintsResponse(BaseModel):
    hints: list[Hint]


class GuessRequest(BaseModel):
    region_id: str


class SoloGuessResponse(BaseModel):
    correct: bool
    attempt: int
    attempts_left: int
    distance_km: float
    heat: Heat
    points: int
    answer_region_id: str | None  # null, поки є спроби і не вгадано


# ---- Card ----
class CardRegion(BaseModel):
    id: str
    name_uk: str


class CardMetric(BaseModel):
    metric_id: str
    title_uk: str
    unit: str | None
    value: float | None
    value_text: str | None = None
    ukraine_avg: float | None
    rank: int | None
    n_ranked: int | None
    source_name: str | None
    source_url: str | None


class SeriesPoint(BaseModel):
    period: str
    value: float


class Card(BaseModel):
    region: CardRegion
    metrics: list[CardMetric]
    highlights: list[str]
    series: dict[str, list[SeriesPoint]]


# ---- Rooms ----
class RoomCreated(BaseModel):
    code: str
    host_key: str
    join_url: str
    qr_svg: str


class HostAction(BaseModel):
    host_key: str


class JoinRequest(BaseModel):
    name: str


class JoinResponse(BaseModel):
    player_id: str


class RoomGuessRequest(BaseModel):
    player_id: str
    region_id: str


class RoomGuessResponse(BaseModel):
    region_id: str


class Player(BaseModel):
    id: str
    name: str
    score: int


class RevealGuess(BaseModel):
    player_id: str
    name: str
    region_id: str
    distance_km: float
    heat: Heat
    points: int


class Reveal(BaseModel):
    answer_region_id: str
    guesses: list[RevealGuess]
    distribution: dict[str, int]
    card: Card | None


class LeaderboardRow(BaseModel):
    name: str
    score: int


class RoomState(BaseModel):
    code: str
    status: RoomStatus
    players: list[Player]
    round_no: int
    total_rounds: int
    ends_at: float | None  # unix-час; null у lobby
    hints: list[Hint]
    answered: int
    total: int
    my_guess: str | None = None
    reveal: Reveal | None = None
    leaderboard: list[LeaderboardRow]
