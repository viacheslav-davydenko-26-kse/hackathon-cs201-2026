"""Картка області. Власник: Матвій (інтерфейс `CardBuilder` — контракт, змінює Слава)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from statistics import mean

from app.repository import Repository
from app.schemas import Card


class CardBuilder(ABC):
    """Контракт `build()` (форма — `app.schemas.Card`, приклад — static/mock/card.json):
      * `metrics`: усі метрики з даними для регіону, найцікавіші першими (фронт малює перші 4 бари);
        `ukraine_avg` — середнє серед регіонів з даними, `None` для categorical;
      * `highlights`: 2–4 короткі речення (можна брати `text_uk` фактів з найбільшим info);
      * `series`: metric_id → точки за зростанням period (щонайменше alerts_count, якщо є);
      * `RegionNotFound` для невідомого id. Працює й для неігрових регіонів (з тим, що є).
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    @abstractmethod
    def build(self, region_id: str) -> Card: ...

    def ukraine_avg(self, metric_id: str) -> float | None:
        values = [rm.value for rm in self.repo.region_metrics(metric_id=metric_id) if rm.value is not None]
        return mean(values) if values else None


class DefaultCardBuilder(CardBuilder):
    def build(self, region_id: str) -> Card:
        raise NotImplementedError("DefaultCardBuilder.build — Матвій")
