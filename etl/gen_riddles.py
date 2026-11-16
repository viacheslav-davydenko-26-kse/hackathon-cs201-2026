"""Stretch: офлайн LLM-перефразування фактів у загадки → facts.riddle_uk. Власник: Матвій.

На демо LLM не викликається: результат лежить у БД.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain import Fact


class RiddleWriter(ABC):
    @abstractmethod
    def rewrite(self, facts: list[Fact]) -> dict[int, str]:
        """fact.id → загадка українською, без назви регіону, ≤ 140 символів."""


def main() -> None:
    raise NotImplementedError("gen_riddles — Stretch, Матвій")


if __name__ == "__main__":
    main()
