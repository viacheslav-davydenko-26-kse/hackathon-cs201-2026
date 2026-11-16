"""Налаштування з env-змінних. Власник: Слава."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "db" / "game.sqlite"))
PARSED_DIR = Path(os.getenv("PARSED_DIR", ROOT / "data" / "parsed"))
STATIC_DIR = ROOT / "static"
#: База для join_url/QR, напр. URL cloudflared-тунелю. Не задано → адреса з запиту хоста.
PUBLIC_URL_SET = bool(os.getenv("PUBLIC_URL"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
#: Демо-режим: DEMO_ROUND_SECONDS=30 → раунд 30 с і (якщо TOTAL_ROUNDS не задано) 1 раунд.
_DEMO_SECONDS = os.getenv("DEMO_ROUND_SECONDS")
ROUND_SECONDS = int(_DEMO_SECONDS or os.getenv("ROUND_SECONDS", "35"))
TOTAL_ROUNDS = int(os.getenv("TOTAL_ROUNDS") or (1 if _DEMO_SECONDS else 5))
TOTAL_HINTS = 5
SOLO_MAX_ATTEMPTS = 3
#: 'random' — тимчасовий RandomHintPicker; 'facts' — FactHintPicker Матвія
HINT_PICKER = os.getenv("HINT_PICKER", "facts")
