"""HTTP-флоу соло і кімнати. Власник: Слава. Нереалізоване (501) → xfail."""
from tests.conftest import require_implemented


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_regions(client):
    data = client.get("/api/regions").json()
    assert len(data) == 27
    assert sum(r["playable"] for r in data) == 25
    assert data[0]["name_uk"].startswith("А")


def test_error_shape(client):
    body = client.post("/api/rooms/ABCD/players", json={}).json()
    assert body["error"]["code"] == "validation_error"


def test_solo_flow(client):
    r = require_implemented(client.post("/api/solo/rounds")).json()
    assert len(r["hints"]) == 1
    rid = r["round_id"]
    assert len(client.post(f"/api/solo/rounds/{rid}/hint").json()["hints"]) == 2
    g = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "lviv"}).json()
    assert g["attempt"] == 1
    assert (g["answer_region_id"] is None) != g["finished"]


def test_solo_guess_crimea(client):
    rid = require_implemented(client.post("/api/solo/rounds")).json()["round_id"]
    r = client.post(f"/api/solo/rounds/{rid}/guess", json={"region_id": "crimea"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "region_not_playable"


def test_room_flow(client):
    room = require_implemented(client.post("/api/rooms")).json()
    code, key = room["code"], room["host_key"]
    a = client.post(f"/api/rooms/{code}/players", json={"name": "A"}).json()["player_id"]
    b = client.post(f"/api/rooms/{code}/players", json={"name": "B"}).json()["player_id"]
    assert client.post(f"/api/rooms/{code}/players", json={"name": "a"}).json()["error"]["code"] == "name_taken"
    assert client.post(f"/api/rooms/{code}/start", json={"host_key": "nope"}).status_code == 403
    s = client.post(f"/api/rooms/{code}/start", json={"host_key": key}).json()
    assert s["status"] == "round" and len(s["hints"]) == 1
    for p in (a, b):
        assert client.post(f"/api/rooms/{code}/guess", json={"player_id": p, "region_id": "lviv"}).status_code == 200
    s = client.get(f"/api/rooms/{code}/state", params={"player_id": a}).json()
    assert s["status"] == "reveal"
    assert s["me"]["id"] == a and s["my_guess"] == "lviv"
    assert sum(s["reveal"]["distribution"].values()) == 2
