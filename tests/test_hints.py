"""Підказки: для кожного ігрового регіону 5 штук з однозначною відповіддю. Власник: Матвій."""
import random

import pytest

from app.errors import RegionNotPlayable
from app.game.hints import FactHintPicker, RandomHintPicker, candidates


def test_random_picker_shape(repo):
    hints = RandomHintPicker(repo).pick("lviv", rng=random.Random(0))
    assert [h.index for h in hints] == [0, 1, 2, 3, 4]


def test_not_playable(repo):
    with pytest.raises(RegionNotPlayable):
        RandomHintPicker(repo).pick("crimea")


def test_fact_picker_unique_answer(repo):
    picker = FactHintPicker(repo)
    for region in repo.playable_regions():
        hints = picker.pick(region.id, rng=random.Random(42))
        assert [h.index for h in hints] == [0, 1, 2, 3, 4]
        assert region.name_uk.split()[0][:5].lower() not in " ".join(h.text.lower() for h in hints)
        facts = {(f.metric_id, f.text_uk): f for f in repo.facts(region.id)}
        used = [facts[(h.metric_id, h.text)] for h in hints if (h.metric_id, h.text) in facts]
        assert candidates(used) == {region.id}
