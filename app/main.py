"""FastAPI-застосунок. Запуск: uvicorn app.main:app --host 0.0.0.0 --port 8000. Власник: Слава."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import regions, rooms, solo
from app.config import STATIC_DIR

app = FastAPI(title="ДеЦе? Live")

app.include_router(regions.router)
app.include_router(solo.router)
app.include_router(rooms.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/static/index.html")
