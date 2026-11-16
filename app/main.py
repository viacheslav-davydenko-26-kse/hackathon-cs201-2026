"""FastAPI-застосунок. Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8000. Власник: Слава."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import regions, rooms, solo
from app.errors import GameError
from app.game.scoring import HINT_MULT
from app.schemas import AppConfig, ErrorResponse

# uvicorn налаштовує лише власні логери — логам app.* потрібен свій обробник
_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)-9s %(name)s: %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)

ERROR_RESPONSES = {code: {"model": ErrorResponse} for code in (403, 404, 409, 422, 501, 503)}

app = FastAPI(title="ДеЦе? Live", version="0.1.0", responses=ERROR_RESPONSES)

app.include_router(regions.router)
app.include_router(solo.router)
app.include_router(rooms.router)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


@app.exception_handler(GameError)
def _game_error(_: Request, e: GameError):
    return _error(e.status, e.code, e.message)


@app.exception_handler(NotImplementedError)
def _not_implemented(_: Request, e: NotImplementedError):
    return _error(501, "not_implemented", str(e) or "not implemented")


@app.exception_handler(RequestValidationError)
def _validation(_: Request, e: RequestValidationError):
    return _error(422, "validation_error", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/config", response_model=AppConfig, tags=["meta"])
def get_config():
    return AppConfig(round_seconds=config.ROUND_SECONDS, total_hints=config.TOTAL_HINTS, hint_mult=HINT_MULT,
                     solo_max_attempts=config.SOLO_MAX_ATTEMPTS, public_url=config.PUBLIC_URL)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/static/index.html")
