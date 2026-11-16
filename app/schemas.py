"""Pydantic-моделі = HTTP-контракт бекенд ↔ фронтенд.

Джерело правди. Похідні від нього:
  * docs/openapi.json   — `python -m scripts.export_openapi`
  * static/mock/*.json  — `python -m scripts.export_mocks`
  * static/js/types.js  — JSDoc-типи, вручну тримаємо в синхроні
tests/test_contract.py падає, якщо щось із цього розійшлося. Змінює лише Слава.

Конвенції: JSON, snake_case, час — unix-секунди (float, UTC), відстані — км,
ID регіонів — slug із таблиці regions ('lviv', 'kyiv_city').
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Heat = Literal["hot", "warm", "cool", "cold"]
RoomStatus = Literal["lobby", "round", "reveal", "finished"]
Category = Literal["war", "demography", "cars", "education"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- errors
class ErrorBody(Model):
    code: str = Field(description="Машинний код, див. docs/contract.md → «Помилки»", examples=["room_not_found"])
    message: str = Field(description="Текст для логів/дебагу, не для гравця")


class ErrorResponse(Model):
    error: ErrorBody


# ---------------------------------------------------------------- common
class AppConfig(Model):
    round_seconds: int = Field(description="Тривалість раунду в кімнаті")
    total_hints: int = Field(5, description="Скільки підказок у раунді")
    hint_mult: list[float] = Field(description="Множник балів за індексом останньої відкритої підказки")
    solo_max_attempts: int = 3
    public_url: str = Field(description="База для посилань/QR, напр. URL тунелю")


class Region(Model):
    id: str = Field(examples=["lviv"])
    name_uk: str = Field(examples=["Львівська область"])
    short_uk: str = Field(examples=["Львівщина"])
    playable: bool = Field(description="false → сіра область, клік ігнорується")
    lat: float | None
    lon: float | None


class Hint(Model):
    index: int = Field(ge=0, le=4, description="0 = найважча (відкривається першою)")
    text: str = Field(examples=["Тут найпопулярніший предмет на вибір — історія України"])
    metric_id: str
    category: Category


# ---------------------------------------------------------------- solo
class SoloRound(Model):
    round_id: str
    total_hints: int = 5
    max_attempts: int = 3
    hints: list[Hint] = Field(description="Відкриті на зараз підказки; на старті рівно 1")


class HintsResponse(Model):
    hints: list[Hint] = Field(description="УСІ відкриті підказки (не лише нова)")


class GuessRequest(Model):
    region_id: str


class SoloGuessResponse(Model):
    correct: bool
    attempt: int = Field(ge=1, description="Номер цієї спроби, 1-based")
    attempts_left: int = Field(ge=0)
    finished: bool = Field(description="true → раунд закрито (вгадано або спроби вичерпано)")
    distance_km: float = Field(ge=0, description="Між центроїдами, округлено до 0.1 (бали/heat — з неокругленої); 0 якщо correct")
    heat: Heat
    points: int = Field(ge=0, description="Бали за ЦЮ спробу")
    total_points: int = Field(ge=0, description="Сума за раунд")
    answer_region_id: str | None = Field(description="null, поки раунд не finished")


# ---------------------------------------------------------------- card
class CardRegion(Model):
    id: str
    name_uk: str


class CardMetric(Model):
    metric_id: str
    title_uk: str
    unit: str | None
    category: Category
    value: float | None = Field(description="null для categorical")
    value_text: str | None = Field(None, description="Лише для categorical")
    ukraine_avg: float | None = Field(description="Середнє серед регіонів з даними; null для categorical")
    rank: int | None = Field(description="1 = найбільше значення")
    n_ranked: int | None
    higher_is: Literal["better", "worse", "neutral"] = "neutral"
    year: int | None = None
    source_name: str | None
    source_url: str | None


class SeriesPoint(Model):
    period: str = Field(examples=["2025-03"])
    value: float


class Card(Model):
    region: CardRegion
    metrics: list[CardMetric] = Field(description="Відсортовані за важливістю; фронт показує перші 4 як бари")
    highlights: list[str] = Field(description="2–4 короткі речення-висновки")
    series: dict[str, list[SeriesPoint]] = Field(description="metric_id → точки за зростанням period")


# ---------------------------------------------------------------- rooms
class RoomCreated(Model):
    code: str = Field(pattern=r"^[A-Z0-9]{4}$", examples=["K7QF"])
    host_key: str = Field(description="Секрет хоста; тримати лише в host.html")
    join_url: str = Field(examples=["https://xxx.trycloudflare.com/static/play.html?room=K7QF"])
    qr_svg: str = Field(description="Готовий <svg>…</svg> для вставки через innerHTML")


class HostAction(Model):
    host_key: str


class JoinRequest(Model):
    name: str = Field(min_length=1, max_length=20)


class JoinResponse(Model):
    player_id: str


class RoomGuessRequest(Model):
    player_id: str
    region_id: str


class RoomGuessResponse(Model):
    region_id: str


class Player(Model):
    id: str
    name: str
    score: int


class RevealGuess(Model):
    player_id: str
    name: str
    region_id: str
    distance_km: float
    heat: Heat
    points: int = Field(description="За раунд, разом із бонусом швидкості")


class Reveal(Model):
    answer_region_id: str
    guesses: list[RevealGuess] = Field(description="Лише ті, хто відповів")
    distribution: dict[str, int] = Field(description="region_id → кількість відповідей")
    card: Card | None = Field(description="null, якщо картка ще не реалізована/впала")


class LeaderboardRow(Model):
    player_id: str
    name: str
    score: int
    delta: int = Field(0, description="Скільки додано в останньому раунді")


class RoomState(Model):
    code: str
    status: RoomStatus
    server_now: float = Field(description="Час сервера; фронт рахує таймер як ends_at - server_now")
    players: list[Player] = Field(description="У порядку приєднання")
    round_no: int = Field(description="1-based; 0 у lobby")
    total_rounds: int
    started_at: float | None = Field(description="Старт поточного раунду; null у lobby")
    ends_at: float | None = Field(description="Дедлайн поточного раунду; null у lobby/finished")
    next_hint_at: float | None = Field(description="Коли відкриється наступна підказка; null, якщо всі відкриті або не round")
    hints: list[Hint] = Field(description="Відкриті на зараз; у reveal — усі 5")
    answered: int
    total: int
    me: Player | None = Field(None, description="Якщо передано відомий player_id")
    my_guess: str | None = Field(None, description="region_id відповіді гравця в поточному раунді")
    reveal: Reveal | None = Field(None, description="Лише в статусах reveal/finished")
    leaderboard: list[LeaderboardRow] = Field(description="Відсортований за score спадно")
