"""Канонічні регіони і зведення будь-якого написання назви до нашого slug. Власник: Ілля.

    normalize_region("Львівська обл.")  -> "lviv"
    normalize_region("м.Київ")          -> "kyiv_city"
    normalize_region("UA-46")           -> "lviv"
    normalize_region("Марс")            -> UnknownRegion (KeyError) з сирою назвою в повідомленні
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from app.domain import RegionInfo
from app.repository import region_from_row

PARSED_REGIONS = Path(__file__).resolve().parent.parent / "data" / "parsed" / "regions.csv"

#: Додаткові написання (вже після normalize_text). Ілля доповнює, коли normalize_region падає.
EXTRA_ALIASES: dict[str, str] = {
    "київ": "kyiv_city",
    "kyiv city": "kyiv_city",
    "kiev": "kyiv_city",
    "київська": "kyiv_obl",
    "ар крим": "crimea",
    "автономна республіка крим": "crimea",
    "крим": "crimea",
    "севастополь": "sevastopol",
}

_STOP = re.compile(r"\b(області|область|обл|місто|м)\b\.?")
_APOS = re.compile(r"[’'ʼ`´‘]")
_LAT_TO_CYR = str.maketrans({"i": "і", "a": "а", "e": "е", "o": "о", "c": "с", "p": "р", "x": "х", "y": "у"})


class UnknownRegion(KeyError):
    pass


def normalize_text(raw: str) -> str:
    """lower, уніфіковані апострофи, без «область/обл./м.», латинські двійники → кирилиця (якщо є кирилиця)."""
    s = _APOS.sub("'", str(raw)).strip().lower().replace(".", ". ")
    if re.search(r"[а-яіїєґ]", s):
        s = s.translate(_LAT_TO_CYR)
    s = _STOP.sub(" ", s)
    return re.sub(r"\s+", " ", s.replace(".", " ")).strip(" -,")


@lru_cache
def load_regions(path: Path = PARSED_REGIONS) -> tuple[RegionInfo, ...]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return tuple(region_from_row(r) for r in csv.DictReader(fh))


@lru_cache
def alias_table(path: Path = PARSED_REGIONS) -> dict[str, str]:
    """normalized alias → region_id (для таблиці region_aliases теж)."""
    table: dict[str, str] = {}
    for r in load_regions(path):
        for alias in (r.id, r.name_uk, r.short_uk, r.name_en, r.iso, r.koatuu2):
            if alias:
                table.setdefault(normalize_text(alias), r.id)
    table.update({normalize_text(k): v for k, v in EXTRA_ALIASES.items()})
    return table


def normalize_region(raw: str) -> str:
    key = normalize_text(raw)
    try:
        return alias_table()[key]
    except KeyError:
        raise UnknownRegion(f"unknown region name {raw!r} (normalized: {key!r}) — add to EXTRA_ALIASES") from None
