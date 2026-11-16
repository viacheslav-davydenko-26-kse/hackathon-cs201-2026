"""Контракт бекенд ↔ фронтенд не розійшовся. Власник: Слава."""
import inspect
import json
from pathlib import Path

import pytest

from app import schemas
from scripts import export_mocks, export_openapi

ROOT = Path(__file__).resolve().parent.parent
MOCK_DIR = ROOT / "static" / "mock"
MOCK_MODELS = {
    "config": schemas.AppConfig, "card": schemas.Card, "solo_round": schemas.SoloRound,
    "solo_hint": schemas.HintsResponse, "solo_guess_wrong": schemas.SoloGuessResponse,
    "solo_guess_correct": schemas.SoloGuessResponse, "solo_guess_failed": schemas.SoloGuessResponse,
    "room_created": schemas.RoomCreated, "room_join": schemas.JoinResponse, "room_guess": schemas.RoomGuessResponse,
    "room_state_lobby": schemas.RoomState, "room_state_round": schemas.RoomState,
    "room_state_reveal": schemas.RoomState, "room_state_finished": schemas.RoomState,
    "error": schemas.ErrorResponse,
}


@pytest.mark.parametrize("name,model", MOCK_MODELS.items())
def test_mock_matches_schema(name, model):
    model.model_validate_json((MOCK_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_regions_mock_matches_schema():
    data = json.loads((MOCK_DIR / "regions.json").read_text(encoding="utf-8"))
    assert len(data) == 27
    for r in data:
        schemas.Region.model_validate(r)


def test_mocks_are_up_to_date():
    for name, obj in export_mocks.mocks().items():
        assert (MOCK_DIR / f"{name}.json").read_text(encoding="utf-8") == export_mocks.dump(obj), \
            f"static/mock/{name}.json застарів: python -m scripts.export_mocks"


def test_openapi_is_up_to_date():
    assert (ROOT / "docs" / "openapi.json").read_text(encoding="utf-8") == export_openapi.render(), \
        "docs/openapi.json застарів: python -m scripts.export_openapi"


def test_every_api_function_mocked():
    api_js = (ROOT / "static" / "js" / "api.js").read_text(encoding="utf-8")
    for name in MOCK_MODELS:
        if name.startswith(("solo_guess_", "room_state_", "error")):
            continue
        assert f"'{name}'" in api_js, f"api.js не використовує мок {name}"


def test_types_js_mentions_every_model():
    types_js = (ROOT / "static" / "js" / "types.js").read_text(encoding="utf-8")
    skip = {"Model", "ErrorResponse", "HostAction", "JoinRequest", "JoinResponse", "GuessRequest",
            "RoomGuessRequest", "RoomGuessResponse", "HintsResponse", "CardRegion", "SeriesPoint", "ErrorBody"}
    models = [n for n, c in inspect.getmembers(schemas, inspect.isclass)
              if issubclass(c, schemas.Model) and n not in skip]
    for name in models:
        assert f"{{object}} {name}" in types_js or f"}} {name} */" in types_js, \
            f"static/js/types.js не описує {name}"
        fields = schemas.__dict__[name].model_fields
        for field in fields:
            assert field in types_js, f"types.js: {name}.{field} відсутнє"
