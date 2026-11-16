"""Вибір регіону + підказок для нового раунду (спільне для solo і rooms). Власник: Слава."""
from __future__ import annotations

import random
from collections.abc import Collection

from app.errors import DataUnavailable
from app.game.hints import HintPicker
from app.schemas import Hint


def pick_round(picker: HintPicker, rng: random.Random,
               exclude: Collection[str] = ()) -> tuple[str, list[Hint]]:
    """Випадковий ігровий регіон (спершу ті, що не в `exclude`) і його підказки.

    Регіон, для якого picker кидає DataUnavailable, пропускається (контракт D1).
    DataUnavailable — лише якщо не підходить жоден регіон.
    """
    playable = [r.id for r in picker.repo.playable_regions()]
    fresh = [r for r in playable if r not in exclude]
    used = [r for r in playable if r in exclude]
    rng.shuffle(fresh)
    rng.shuffle(used)
    for region_id in fresh + used:
        try:
            return region_id, picker.pick(region_id, rng=rng)
        except DataUnavailable:
            continue
    raise DataUnavailable("no playable region can produce a valid round")
