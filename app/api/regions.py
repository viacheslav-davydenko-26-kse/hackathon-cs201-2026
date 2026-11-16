"""/api/regions. Власник: Слава."""
from fastapi import APIRouter, HTTPException

from app.db import query
from app.schemas import Card, Region

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("", response_model=list[Region])
def list_regions():
    return query("SELECT id, name_uk, short_uk, playable, lat, lon FROM regions ORDER BY name_uk")


@router.get("/{region_id}/card", response_model=Card)
def region_card(region_id: str):
    # TODO(Матвій): app.game.card.build_card(region_id)
    raise HTTPException(501, "not implemented")
