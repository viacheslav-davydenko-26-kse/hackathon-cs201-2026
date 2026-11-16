"""Регенерує static/mock/*.json — приклади відповідей API, валідні за app/schemas.py.

    python -m scripts.export_mocks

Фронт читає їх при USE_MOCK = true (static/js/api.js). Назва файлу = ключ у MOCK_FILES в api.js.
Значення реалістичні (справжні регіони), але бали/підказки вигадані.
"""
import json
from pathlib import Path

from app.config import PARSED_DIR, PUBLIC_URL
from app.game.scoring import HINT_MULT
from app.qr import join_url, qr_svg
from app.schemas import (
    AppConfig, Card, CardMetric, CardRegion, ErrorBody, ErrorResponse, Hint, HintsResponse, JoinResponse,
    LeaderboardRow, Player, Region, Reveal, RevealGuess, RoomCreated, RoomGuessResponse, RoomState,
    SeriesPoint, SoloGuessResponse, SoloRound,
)
from app.repository import CsvRepository

OUT = Path(__file__).resolve().parent.parent / "static" / "mock"
T0 = 1_763_300_000.0  # фіксований «зараз», щоб моки не змінювались між запусками

HINTS = [
    Hint(index=0, text="Тут найпопулярніший предмет НМТ на вибір, крім англійської, — історія України",
         metric_id="nmt_top_elective_non_eng", category="education"),
    Hint(index=1, text="Тривоги тут тривали в середньому 65 хвилин — одне з найнижчих значень",
         metric_id="alerts_avg_minutes", category="war"),
    Hint(index=2, text="Народжуваність тут на 20% вища за середню по Україні",
         metric_id="births_per_1000", category="demography"),
    Hint(index=3, text="Тут 3-є місце з 25 за кількістю учасників НМТ",
         metric_id="nmt_participants", category="education"),
    Hint(index=4, text="Обласний центр — найбільше місто заходу України",
         metric_id="population", category="demography"),
]


def mocks() -> dict[str, object]:
    repo = CsvRepository(PARSED_DIR)
    regions = [Region(id=r.id, name_uk=r.name_uk, short_uk=r.short_uk, playable=r.playable, lat=r.lat, lon=r.lon)
               for r in repo.regions()]
    card = Card(
        region=CardRegion(id="lviv", name_uk="Львівська область"),
        metrics=[
            CardMetric(metric_id="births_per_1000", title_uk="Народжуваність", unit="на 1000 мешканців",
                       category="demography", value=8.1, ukraine_avg=6.7, rank=4, n_ranked=25, higher_is="better",
                       year=2021, source_name="Держстат", source_url="https://data.gov.ua/dataset/8ce892f8-a4c4-4c17-bdcf-b0537e2d2de4"),
            CardMetric(metric_id="alerts_hours", title_uk="Сумарна тривалість тривог", unit="годин за період 1 січня – 20 серпня 2025",
                       category="war", value=322.5, ukraine_avg=812.4, rank=22, n_ranked=25, higher_is="worse",
                       year=2025, source_name="Повітряні тривоги (Vadimkin)",
                       source_url="https://github.com/Vadimkin/ukrainian-air-raid-sirens-dataset"),
            CardMetric(metric_id="nmt_avg_math", title_uk="Середній бал НМТ з математики", unit="балів (100–200)",
                       category="education", value=146.2, ukraine_avg=141.8, rank=3, n_ranked=25, higher_is="better",
                       year=2025, source_name="УЦОЯО", source_url="https://zno.testportal.com.ua/opendata"),
            CardMetric(metric_id="divorces_per_100_marriages", title_uk="Розлучень на 100 шлюбів", unit="на 100 шлюбів",
                       category="demography", value=38.0, ukraine_avg=49.5, rank=24, n_ranked=25, higher_is="worse",
                       year=2021, source_name="Держстат", source_url="https://data.gov.ua/"),
            CardMetric(metric_id="nmt_top_elective_non_eng", title_uk="Найпопулярніший предмет, крім англійської",
                       unit=None, category="education", value=None, value_text="історія України",
                       ukraine_avg=None, rank=None, n_ranked=None, year=2025, source_name="УЦОЯО",
                       source_url="https://zno.testportal.com.ua/opendata"),
        ],
        highlights=["У топ-5 за народжуваністю", "Утричі менше годин тривоги, ніж у середньому по Україні",
                    "3-є місце за балом НМТ з математики"],
        series={"alerts_count": [SeriesPoint(period=f"2025-{m:02d}", value=v)
                                 for m, v in enumerate([22, 18, 25, 20, 31, 27, 24, 19, 21, 26, 23, 17], 1)]},
    )
    players = [Player(id="p_a1", name="Оля", score=1450), Player(id="p_b2", name="Журі №1", score=1220),
               Player(id="p_c3", name="Тарас", score=310)]
    lb = [LeaderboardRow(player_id=p.id, name=p.name, score=p.score, delta=d) for p, d in zip(players, [880, 700, 0])]
    base = dict(code="K7QF", total_rounds=5, players=players, total=3)
    url = join_url("K7QF", PUBLIC_URL)
    guesses = [RevealGuess(player_id="p_a1", name="Оля", region_id="lviv", distance_km=0, heat="hot", points=880),
               RevealGuess(player_id="p_b2", name="Журі №1", region_id="ternopil", distance_km=118.4, heat="hot", points=210)]
    reveal = Reveal(answer_region_id="lviv", guesses=guesses, distribution={"lviv": 1, "ternopil": 1}, card=card)
    return {
        "config": AppConfig(round_seconds=35, total_hints=5, hint_mult=HINT_MULT, solo_max_attempts=3,
                            public_url=PUBLIC_URL),
        "regions": regions,
        "solo_round": SoloRound(round_id="r_9f2c1a", hints=HINTS[:1]),
        "solo_hint": HintsResponse(hints=HINTS[:2]),
        "solo_guess_wrong": SoloGuessResponse(correct=False, attempt=1, attempts_left=2, finished=False,
                                              distance_km=212.7, heat="warm", points=91, total_points=91,
                                              answer_region_id=None),
        "solo_guess_correct": SoloGuessResponse(correct=True, attempt=2, attempts_left=1, finished=True,
                                                distance_km=0, heat="hot", points=400, total_points=491,
                                                answer_region_id="lviv"),
        "solo_guess_failed": SoloGuessResponse(correct=False, attempt=3, attempts_left=0, finished=True,
                                               distance_km=640.2, heat="cold", points=0, total_points=91,
                                               answer_region_id="lviv"),
        "card": card,
        "room_created": RoomCreated(code="K7QF", host_key="hk_3b9e0d7a", join_url=url, qr_svg=qr_svg(url)),
        "room_join": JoinResponse(player_id="p_a1"),
        "room_guess": RoomGuessResponse(region_id="lviv"),
        "room_state_lobby": RoomState(**base, status="lobby", server_now=T0, round_no=0, started_at=None, ends_at=None,
                  next_hint_at=None, hints=[], answered=0,
                  leaderboard=[LeaderboardRow(player_id=p.id, name=p.name, score=0) for p in players]),
        "room_state_round": RoomState(**base, status="round", server_now=T0 + 15, round_no=2, started_at=T0,
                                      ends_at=T0 + 35, next_hint_at=T0 + 21, hints=HINTS[:3], answered=1,
                                      me=players[0], my_guess="lviv", leaderboard=lb),
        "room_state_reveal": RoomState(**base, status="reveal", server_now=T0 + 36, round_no=2, started_at=T0,
                                       ends_at=T0 + 35, next_hint_at=None, hints=HINTS, answered=2,
                                       me=players[0], my_guess="lviv", reveal=reveal, leaderboard=lb),
        "room_state_finished": RoomState(**base, status="finished", server_now=T0 + 400, round_no=5,
                                         started_at=None, ends_at=None, next_hint_at=None, hints=HINTS,
                                         answered=2, reveal=reveal, leaderboard=lb),
        "error": ErrorResponse(error=ErrorBody(code="room_not_found", message="unknown room 'ZZZZ'")),
    }


def dump(obj) -> str:
    data = [x.model_dump(mode="json") for x in obj] if isinstance(obj, list) else obj.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, obj in mocks().items():
        (OUT / f"{name}.json").write_text(dump(obj), encoding="utf-8")
    print(f"wrote {len(mocks())} files to {OUT}")
