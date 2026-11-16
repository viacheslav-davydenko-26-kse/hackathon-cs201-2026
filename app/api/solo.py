"""/api/solo. Власник: Слава."""
from fastapi import APIRouter, HTTPException

from app.schemas import GuessRequest, HintsResponse, SoloGuessResponse, SoloRound

router = APIRouter(prefix="/api/solo", tags=["solo"])


@router.post("/rounds", response_model=SoloRound)
def create_round():
    raise HTTPException(501, "not implemented")


@router.post("/rounds/{round_id}/hint", response_model=HintsResponse)
def next_hint(round_id: str):
    raise HTTPException(501, "not implemented")


@router.post("/rounds/{round_id}/guess", response_model=SoloGuessResponse)
def guess(round_id: str, body: GuessRequest):
    raise HTTPException(501, "not implemented")
