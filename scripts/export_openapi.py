"""Регенерує docs/openapi.json зі схем FastAPI:  python -m scripts.export_openapi"""
import json
from pathlib import Path

from app.main import app

OUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")
