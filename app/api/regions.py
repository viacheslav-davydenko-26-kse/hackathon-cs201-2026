"""/api/regions. Власник: Слава."""
from fastapi import APIRouter, Depends

from app.deps import get_card_builder, get_repository
from app.game.card import CardBuilder
from app.repository import Repository
from app.schemas import Card, Region

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("", response_model=list[Region])
def list_regions(repo: Repository = Depends(get_repository)):
    return [Region(id=r.id, name_uk=r.name_uk, short_uk=r.short_uk, playable=r.playable, lat=r.lat, lon=r.lon)
            for r in repo.regions()]


@router.get("/{region_id}/card", response_model=Card, responses={404: {}})
def region_card(region_id: str, cards: CardBuilder = Depends(get_card_builder)):
    return cards.build(region_id)
