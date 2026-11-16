"""HTTP flows using shipped SQLite data and the real picker; no stub hints."""
from __future__ import annotations

import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.deps import get_repository, get_rooms, get_solo
from app.game.card import DefaultCardBuilder
from app.game.hints import FactHintPicker
from app.game.rooms import InMemoryRoomManager
from app.game.solo import InMemorySoloService
from app.main import app
from app.repository import SqliteRepository


@pytest.fixture
def real_app():
    repo = SqliteRepository(Path(__file__).resolve().parents[1] / "db/game.sqlite")
    picker = FactHintPicker(repo)
    now = [1000.0]
    solo = InMemorySoloService(repo, picker, clock=lambda: now[0], rng=random.Random(42))
    rooms = InMemoryRoomManager(
        repo, picker, DefaultCardBuilder(repo), clock=lambda: now[0],
        round_seconds=35, total_rounds=2, rng=random.Random(42),
    )
    previous = dict(app.dependency_overrides)
    app.dependency_overrides.update({
        get_repository: lambda: repo, get_solo: lambda: solo, get_rooms: lambda: rooms,
    })
    try:
        with TestClient(app) as client:
            yield client, repo, now
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def answer_from_hints(hints, repo):
    """Resolve the public clues against stored facts, without reading game state."""
    compatible = {r.id for r in repo.playable_regions()}
    for hint in hints:
        matches = [
            fact for fact in repo.facts()
            if fact.metric_id == hint["metric_id"]
            and (fact.riddle_uk or fact.text_uk) == hint["text"]
        ]
        assert matches, f"Hint has no matching source fact: {hint}"
        compatible &= set().union(*(fact.consistent for fact in matches))
    assert len(compatible) == 1, f"Ambiguous public clues: {compatible}"
    return compatible.pop()


def checked(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_solo_completes_using_real_data_and_hints(real_app):
    client, repo, _ = real_app
    started = checked(client.post("/api/solo/rounds"))
    assert len(started["hints"]) == 1
    assert "answer_region_id" not in started
    round_id = started["round_id"]
    hints = started["hints"]
    for count in range(2, 6):
        revealed = checked(client.post(f"/api/solo/rounds/{round_id}/hint"))
        assert revealed["hints"][:len(hints)] == hints
        hints = revealed["hints"]
        assert len(hints) == count
    answer = answer_from_hints(hints, repo)
    result = checked(client.post(
        f"/api/solo/rounds/{round_id}/guess", json={"region_id": answer},
    ))
    assert result["correct"] and result["finished"]
    assert result["answer_region_id"] == answer
    assert result["points"] == result["total_points"] == 300
    assert result["distance_km"] == 0 and result["heat"] == "hot"
    assert client.post(f"/api/solo/rounds/{round_id}/hint").status_code == 409


def test_multiplayer_completes_two_rounds_using_real_picker(real_app):
    client, repo, now = real_app
    created = checked(client.post("/api/rooms"))
    base = f"/api/rooms/{created['code']}"
    ids = [checked(client.post(base + "/players", json={"name": name}))["player_id"]
           for name in ("Alice", "Bob")]
    host = {"host_key": created["host_key"]}
    state = checked(client.post(base + "/start", json=host))
    answers = []
    for round_no in (1, 2):
        assert state["status"] == "round" and state["round_no"] == round_no
        assert state["reveal"] is None and len(state["hints"]) == 1
        now[0] += 28  # Reveal all five hints while seven seconds remain.
        state = checked(client.get(base + "/state"))
        assert len(state["hints"]) == 5
        answer = answer_from_hints(state["hints"], repo)
        answers.append(answer)
        for player in ids:
            checked(client.post(base + "/guess", json={"player_id": player, "region_id": answer}))
        state = checked(client.get(base + "/state"))
        assert state["status"] == "reveal"
        assert state["reveal"]["answer_region_id"] == answer
        assert state["reveal"]["distribution"] == {answer: 2}
        assert [g["points"] for g in state["reveal"]["guesses"]] == [320, 320]
        assert [p["score"] for p in state["leaderboard"]] == [320 * round_no] * 2
        state = checked(client.post(base + "/next", json=host))
    assert len(set(answers)) == 2
    assert state["status"] == "finished"
    assert [p["player_id"] for p in state["leaderboard"]] == ids

