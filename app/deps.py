"""Збірка залежностей. Єдине місце, де вирішується, ЯКА реалізація інтерфейсу працює.

Щоб підмінити реалізацію в тестах:  app.dependency_overrides[get_solo] = lambda: FakeSolo()
Власник: Слава.
"""
from functools import lru_cache

from app import config
from app.game.card import CardBuilder, DefaultCardBuilder
from app.game.hints import FactHintPicker, HintPicker, RandomHintPicker
from app.game.rooms import InMemoryRoomManager, RoomManager
from app.game.solo import InMemorySoloService, SoloService
from app.repository import CsvRepository, Repository, SqliteRepository


@lru_cache
def get_repository() -> Repository:
    """game.sqlite, якщо вона є; інакше data/parsed/*.csv (без фактів)."""
    if config.DB_PATH.exists():
        return SqliteRepository(config.DB_PATH)
    return CsvRepository(config.PARSED_DIR)


@lru_cache
def get_hint_picker() -> HintPicker:
    cls = FactHintPicker if config.HINT_PICKER == "facts" else RandomHintPicker
    return cls(get_repository())


@lru_cache
def get_card_builder() -> CardBuilder:
    return DefaultCardBuilder(get_repository())


@lru_cache
def get_solo() -> SoloService:
    return InMemorySoloService(get_repository(), get_hint_picker())


@lru_cache
def get_rooms() -> RoomManager:
    return InMemoryRoomManager(get_repository(), get_hint_picker(), get_card_builder())
