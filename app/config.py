"""Налаштування з env-змінних. Власник: Слава."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "db" / "game.sqlite"))
STATIC_DIR = ROOT / "static"
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
ROUND_SECONDS = int(os.getenv("DEMO_ROUND_SECONDS") or os.getenv("ROUND_SECONDS", "35"))
TOTAL_ROUNDS = int(os.getenv("TOTAL_ROUNDS", "5"))
TOTAL_HINTS = 5
