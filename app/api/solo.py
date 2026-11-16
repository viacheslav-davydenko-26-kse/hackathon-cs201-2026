"""/api/solo. Власник: Слава."""
from fastapi import APIRouter, Depends

from app.deps import get_solo
from app.game.solo import SoloService
from app.schemas import GuessRequest, HintsResponse, SoloGuessResponse, SoloRound

router = APIRouter(prefix="/api/solo", tags=["solo"])


@router.post("/rounds", response_model=SoloRound)
def create_round(solo: SoloService = Depends(get_solo)):
    return solo.start_round()


@router.post("/rounds/{round_id}/hint", response_model=HintsResponse, responses={404: {}, 409: {}})
def next_hint(round_id: str, solo: SoloService = Depends(get_solo)):
    return solo.reveal_hint(round_id)


@router.post("/rounds/{round_id}/guess", response_model=SoloGuessResponse, responses={404: {}, 409: {}, 422: {}})
def guess(round_id: str, body: GuessRequest, solo: SoloService = Depends(get_solo)):
    return solo.guess(round_id, body.region_id)
