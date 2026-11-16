"""HTTP-флоу соло і кімнат + граничні випадки з docs/contract.md §9. Власник: Слава.

Детерміновано: фейковий годинник (FakeClock) і picker, який «загадує» лише дозволені регіони.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.deps import get_repository, get_rooms, get_solo
from app.errors import DataUnavailable
from app.game.card import CardBuilder
from app.game.hints import HintPicker
from app.game.rooms import InMemoryRoomManager
from app.game.scoring import HINT_MULT, haversine, points, speed_bonus
from app.game.solo import InMemorySoloService
from app.main import app
from app.schemas import Hint

ROUND = 35.0
STEP = ROUND / 5


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def tick(self, dt: float) -> None:
        self.t += dt


class StubPicker(HintPicker):
    """Загадує лише регіони з `allowed` (решта → DataUnavailable, як у контракті D1)."""

    def __init__(self, repo, allowed=("lviv",)):
        super().__init__(repo)
        self.allowed = list(allowed)

    def pick(self, region_id, n=5, rng=None):
        self._require_playable(region_id)
        if region_id not in self.allowed:
            raise DataUnavailable(region_id)
        return [Hint(index=i, text=f"hint {i}", metric_id="alerts_count", category="war") for i in range(n)]


class BrokenCards(CardBuilder):
    def build(self, region_id):
        raise RuntimeError("boom")


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_client(clock):
    repo = get_repository()

    def make(allowed=("lviv",), total_rounds=2, cards=None):
        picker = StubPicker(repo, allowed)
        solo = InMemorySoloService(repo, picker, clock=clock)
        rooms = InMemoryRoomManager(repo, picker, cards, clock=clock, round_seconds=int(ROUND),
                                    total_rounds=total_rounds)
        app.dependency_overrides[get_solo] = lambda: solo
        app.dependency_overrides[get_rooms] = lambda: rooms
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client):
    return make_client()


def dist(a: str, b: str) -> float:
    repo = get_repository()
    ra, rb = repo.region(a), repo.region(b)
    return haversine(ra.lat, ra.lon, rb.lat, rb.lon)


def err(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


# ====================================================================== базове
def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_regions(client):
    data = client.get("/api/regions").json()
    assert len(data) == 27
    assert sum(r["playable"] for r in data) == 25
    assert data[0]["name_uk"].startswith("А")


def test_config(client):
    cfg = client.get("/api/config").json()
    assert cfg["hint_mult"] == HINT_MULT and cfg["total_hints"] == 5


def test_validation_error_shape(client):
    assert err(client.post("/api/rooms/ABCD/players", json={})) == (422, "validation_error")


# ====================================================================== соло
def solo_start(c):
    return c.post("/api/solo/rounds").json()["round_id"]


def test_solo_happy_path(client):
    r = client.post("/api/solo/rounds").json()
    assert len(r["hints"]) == 1 and r["max_attempts"] == 3 and r["total_hints"] == 5
    rid = r["round_id"]
    assert [h["index"] for h in client.post(f"/api/solo/rounds/{rid}/hint").json()["hints"]] == [0, 1]
    g = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"}).json()
    assert g == {"correct": True, "attempt": 1, "attempts_left": 2, "finished": True, "distance_km": 0.0,
                 "heat": "hot", "points": 800, "total_points": 800, "answer_region_id": "lviv"}


def test_solo_s1_wrong_guesses_accumulate(client):
    rid = solo_start(client)
    g1 = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "ternopil"}).json()
    d = dist("ternopil", "lviv")
    assert g1["points"] == points(False, d, 0, 1) > 0
    assert g1["distance_km"] == round(d, 1) and g1["answer_region_id"] is None and not g1["finished"]
    g2 = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"}).json()
    assert g2["points"] == points(True, 0, 0, 2) == 500
    assert g2["total_points"] == g1["points"] + 500


def test_solo_three_wrong_finishes(client):
    rid = solo_start(client)
    for i, region in enumerate(["kharkiv", "odesa", "sumy"], 1):
        g = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": region}).json()
        assert g["attempt"] == i and g["finished"] == (i == 3)
    assert g["answer_region_id"] == "lviv" and g["attempts_left"] == 0


def test_solo_s2_repeat_region_costs_nothing(client):
    rid = solo_start(client)
    client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "odesa"})
    assert err(client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "odesa"})) == (409, "already_guessed")
    assert client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "kharkiv"}).json()["attempt"] == 2


def test_solo_s3_invalid_regions_cost_nothing(client):
    rid = solo_start(client)
    assert err(client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "mars"})) == (404, "region_not_found")
    assert err(client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "crimea"})) == (422, "region_not_playable")
    assert client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "odesa"}).json()["attempt"] == 1


def test_solo_s4_sixth_hint(client):
    rid = solo_start(client)
    for _ in range(4):
        hints = client.post(f"/api/solo/rounds/{rid}/hint").json()["hints"]
    assert len(hints) == 5
    assert err(client.post(f"/api/solo/rounds/{rid}/hint")) == (409, "no_more_hints")


def test_solo_s5_after_finish(client):
    rid = solo_start(client)
    client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"})
    assert err(client.post(f"/api/solo/rounds/{rid}/hint")) == (409, "round_finished")
    assert err(client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"})) == (409, "round_finished")


def test_solo_points_use_open_hints(client):
    rid = solo_start(client)
    for _ in range(4):
        client.post(f"/api/solo/rounds/{rid}/hint")
    assert client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"}).json()["points"] == 300


def test_solo_unknown_round(client):
    assert err(client.post("/api/solo/rounds/r_nope/hint")) == (404, "round_not_found")


def test_solo_d1_skips_bad_regions(make_client):
    c = make_client(allowed=("odesa",))
    rid = solo_start(c)
    assert c.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "odesa"}).json()["correct"]


def test_solo_d1_no_region_at_all(make_client):
    assert err(make_client(allowed=()).post("/api/solo/rounds")) == (503, "data_unavailable")


# ====================================================================== кімнати
class Room:
    def __init__(self, c: TestClient):
        self.c = c
        r = c.post("/api/rooms").json()
        self.code, self.key = r["code"], r["host_key"]
        self.created = r

    def join(self, name):
        return self.c.post(f"/api/rooms/{self.code}/players", json={"name": name})

    def pid(self, name):
        return self.join(name).json()["player_id"]

    def start(self, key=None):
        return self.c.post(f"/api/rooms/{self.code}/start", json={"host_key": key or self.key})

    def next(self, key=None):
        return self.c.post(f"/api/rooms/{self.code}/next", json={"host_key": key or self.key})

    def guess(self, pid, region):
        return self.c.post(f"/api/rooms/{self.code}/guess", json={"player_id": pid, "region_id": region})

    def state(self, pid=None):
        return self.c.get(f"/api/rooms/{self.code}/state", params={"player_id": pid} if pid else {}).json()


def test_room_created(client):
    r = Room(client).created
    assert len(r["code"]) == 4 and not set(r["code"]) & set("01OI")
    assert r["join_url"] == f"http://testserver/static/play.html?room={r['code']}"
    assert r["qr_svg"].startswith("<svg")


def test_room_full_flow_and_state_fields(client, clock):
    room = Room(client)
    a, b = room.pid("Оля"), room.pid("Тарас")
    s = room.state()
    assert (s["status"], s["round_no"], s["hints"], s["ends_at"], s["answered"], s["total"]) == ("lobby", 0, [], None, 0, 2)

    s = room.start().json()
    assert s["status"] == "round" and s["round_no"] == 1 and len(s["hints"]) == 1
    assert s["ends_at"] - s["started_at"] == ROUND and s["next_hint_at"] == s["started_at"] + STEP
    assert s["server_now"] == clock.t and s["reveal"] is None

    clock.tick(STEP * 2)                                          # відкрито 3 підказки
    assert len(room.state()["hints"]) == 3
    assert room.guess(a, "lviv").json() == {"region_id": "lviv"}
    s = room.state(a)
    assert s["answered"] == 1 and s["my_guess"] == "lviv" and s["me"]["id"] == a
    clock.tick(STEP)
    room.guess(b, "ternopil")                                     # усі відповіли → reveal

    s = room.state(b)
    assert s["status"] == "reveal" and len(s["hints"]) == 5 and s["next_hint_at"] is None
    rv = s["reveal"]
    assert rv["answer_region_id"] == "lviv" and rv["distribution"] == {"lviv": 1, "ternopil": 1}
    assert [g["player_id"] for g in rv["guesses"]] == [a, b]      # R9: порядок прийняття
    pa = points(True, 0, 2) + speed_bonus(ROUND - 2 * STEP, ROUND)
    pb = points(False, dist("ternopil", "lviv"), 3)
    assert [g["points"] for g in rv["guesses"]] == [pa, pb]
    assert rv["guesses"][1]["distance_km"] == round(dist("ternopil", "lviv"), 1)
    assert [(r["player_id"], r["score"], r["delta"]) for r in s["leaderboard"]] == [(a, pa, pa), (b, pb, pb)]

    s = room.next().json()                                        # раунд 2
    assert s["status"] == "round" and s["round_no"] == 2 and s["my_guess"] is None
    assert [r["delta"] for r in s["leaderboard"]] == [pa, pb]     # delta з попереднього раунду

    clock.tick(ROUND)                                             # дедлайн → reveal, без відповідей
    s = room.state()
    assert s["status"] == "reveal" and s["reveal"]["guesses"] == [] and [r["delta"] for r in s["leaderboard"]] == [0, 0]

    s = room.next().json()
    assert s["status"] == "finished" and s["round_no"] == 2 and s["ends_at"] is None and s["reveal"] is not None
    assert err(room.next()) == (409, "invalid_state")


def test_room_r1_r2_deadline_boundary(client, clock):
    room = Room(client)
    a, b, c = room.pid("A"), room.pid("B"), room.pid("C")
    room.start()
    clock.tick(ROUND - 0.001)
    assert room.guess(a, "lviv").status_code == 200               # R1
    clock.tick(0.001)                                             # рівно ends_at
    assert err(room.guess(b, "lviv")) == (409, "round_finished")  # R2
    assert room.state()["status"] == "reveal"
    assert err(room.guess(c, "lviv")) == (409, "round_finished")


def test_room_r3_guess_in_lobby_and_finished(make_client):
    room = Room(make_client(total_rounds=1))
    a = room.pid("A")
    assert err(room.guess(a, "lviv")) == (409, "invalid_state")
    room.start(); room.guess(a, "lviv"); room.next()
    assert room.state()["status"] == "finished"
    assert err(room.guess(a, "lviv")) == (409, "invalid_state")


def test_room_r4_duplicate_guess(client):
    room = Room(client)
    a, _ = room.pid("A"), room.pid("B")
    room.start()
    room.guess(a, "odesa")
    assert err(room.guess(a, "lviv")) == (409, "already_guessed")
    room.next()
    assert room.state(a)["reveal"]["guesses"][0]["region_id"] == "odesa"


def test_room_r5_check_order(client):
    room = Room(client)
    a = room.pid("A")
    assert err(room.c.post("/api/rooms/ZZZZ/guess", json={"player_id": a, "region_id": "x"})) == (404, "room_not_found")
    assert err(room.guess("p_nope", "mars")) == (404, "player_not_found")
    assert err(room.guess(a, "mars")) == (404, "region_not_found")
    assert err(room.guess(a, "crimea")) == (422, "region_not_playable")
    assert err(room.guess(a, "lviv")) == (409, "invalid_state")


def test_room_r8_leaderboard_ties_by_join_order(client):
    room = Room(client)
    ids = [room.pid(n) for n in ("C", "A", "B")]
    room.start(); room.next()                                     # нікому нічого
    assert [r["player_id"] for r in room.state()["leaderboard"]] == ids


def test_room_r10_no_repeats(make_client):
    room = Room(make_client(allowed=("lviv", "odesa"), total_rounds=3))
    room.pid("A")
    answers = []
    room.start()
    for _ in range(3):
        room.next()
        answers.append(room.state()["reveal"]["answer_region_id"])
        room.next()
    assert sorted(answers[:2]) == ["lviv", "odesa"]                # третій — повтор, бо більше нема


def test_room_host_key(client):
    room = Room(client)
    assert err(room.start("wrong")) == (403, "bad_host_key")
    assert err(room.next("wrong")) == (403, "bad_host_key")
    assert room.start().status_code == 200
    assert err(room.start()) == (409, "invalid_state")


def test_room_join_rules(client):
    room = Room(client)
    room.pid("Оля")
    assert err(room.join("  оля ")) == (409, "name_taken")
    assert err(room.join("   ")) == (422, "invalid_name")
    assert err(room.join("x" * 21)) == (422, "validation_error")
    assert err(client.post("/api/rooms/ZZZZ/players", json={"name": "A"})) == (404, "room_not_found")
    assert room.join("Тарас").status_code == 200
    assert client.post(f"/api/rooms/{room.code.lower()}/players", json={"name": "Lower"}).status_code == 200


def test_room_i1_i3_identity(client):
    room = Room(client)
    a = room.pid("A")
    room.pid("B")
    room.start()
    room.guess(a, "lviv")
    anon = room.state("p_unknown")
    assert anon["me"] is None and anon["my_guess"] is None
    again = room.state(a)                                         # «перезавантаження»
    assert again["me"]["id"] == a and again["my_guess"] == "lviv"


def test_room_i5_i6_join_midgame_and_finished(make_client):
    room = Room(make_client(total_rounds=1))
    a = room.pid("A")
    room.start()
    late = room.pid("Late")
    assert room.state()["total"] == 2
    assert room.guess(late, "lviv").status_code == 200
    room.guess(a, "odesa")
    room.next()
    assert room.state()["status"] == "finished"
    assert err(room.join("Too late")) == (409, "invalid_state")


def test_room_d2_card_failure(make_client, caplog):
    room = Room(make_client(cards=BrokenCards(get_repository())))
    room.pid("A")
    room.start()
    with caplog.at_level(logging.ERROR):
        s = room.next().json()
    assert s["status"] == "reveal" and s["reveal"]["card"] is None
    assert "card for lviv failed" in caplog.text


def test_room_host_can_end_round_early(client):
    room = Room(client)
    room.pid("A")
    room.start()
    assert room.next().json()["status"] == "reveal"
