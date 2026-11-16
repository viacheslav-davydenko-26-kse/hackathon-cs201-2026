"""Room isolation and retry/concurrency checks against the real room manager."""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app.errors import BadHostKey, GameError, PlayerNotFound
from app.game.hints import FactHintPicker
from app.game.rooms import InMemoryRoomManager
from app.repository import SqliteRepository


@pytest.fixture
def manager():
    repo = SqliteRepository(Path(__file__).resolve().parents[1] / "db/game.sqlite")
    return InMemoryRoomManager(
        repo, FactHintPicker(repo), clock=lambda: 1000.0,
        total_rounds=2, round_seconds=35, rng=random.Random(42),
    )


def test_start_guess_and_reveal_do_not_change_another_room(manager):
    a, b = manager.create_room(), manager.create_room()
    a_player = manager.join(a.code, "Alice").player_id
    b_player = manager.join(b.code, "Bob").player_id
    b_before = manager.state(b.code, b_player).model_dump()
    manager.start(a.code, a.host_key)
    manager.guess(a.code, a_player, "lviv")
    assert manager.state(a.code).status == "reveal"
    assert manager.state(b.code, b_player).model_dump() == b_before
    a_before = manager.state(a.code, a_player).model_dump()
    manager.start(b.code, b.host_key)
    manager.guess(b.code, b_player, "odesa")
    assert manager.state(a.code, a_player).model_dump() == a_before
    assert [p.id for p in manager.state(a.code).players] == [a_player]
    assert [p.id for p in manager.state(b.code).players] == [b_player]


def test_host_key_cannot_control_another_room(manager):
    a, b = manager.create_room(), manager.create_room()
    before = manager.state(b.code).model_dump()
    for action in (manager.start, manager.next):
        with pytest.raises(BadHostKey):
            action(b.code, a.host_key)
        assert manager.state(b.code).model_dump() == before


def test_player_identity_is_scoped_to_its_room(manager):
    a, b = manager.create_room(), manager.create_room()
    player = manager.join(a.code, "Alice").player_id
    manager.join(b.code, "Bob")
    manager.start(b.code, b.host_key)
    before = manager.state(b.code).model_dump()
    with pytest.raises(PlayerNotFound):
        manager.guess(b.code, player, "lviv")
    assert manager.state(b.code).model_dump() == before
    anonymous = manager.state(b.code, player)
    assert anonymous.me is None and anonymous.my_guess is None


def test_simultaneous_guesses_accept_exactly_one_answer(manager):
    room = manager.create_room()
    player = manager.join(room.code, "Alice").player_id
    manager.join(room.code, "Bob")  # Keep the round open after Alice answers.
    manager.start(room.code, room.host_key)
    barrier = Barrier(2)

    def submit(region):
        barrier.wait(timeout=5)
        try:
            return "accepted", manager.guess(room.code, player, region).region_id
        except GameError as error:
            return error.code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ["lviv", "odesa"]))
    assert sorted(code for code, _ in results) == ["accepted", "already_guessed"]
    accepted = next(region for code, region in results if code == "accepted")
    state = manager.state(room.code, player)
    assert state.answered == 1 and state.my_guess == accepted
    revealed = manager.next(room.code, room.host_key)
    assert len(revealed.reveal.guesses) == 1
    assert revealed.reveal.guesses[0].region_id == accepted
    assert sum(revealed.reveal.distribution.values()) == 1


def test_polling_and_rejected_retries_never_award_points_twice(manager):
    room = manager.create_room()
    player = manager.join(room.code, "Alice").player_id
    manager.start(room.code, room.host_key)
    manager.guess(room.code, player, "lviv")
    baseline = manager.state(room.code, player).model_dump()
    for _ in range(5):
        assert manager.state(room.code, player).model_dump() == baseline
        with pytest.raises(GameError) as rejected:
            manager.guess(room.code, player, "odesa")
        assert rejected.value.code == "round_finished"
        assert manager.state(room.code, player).model_dump() == baseline

