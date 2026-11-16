"""/api/rooms (REST + polling). Власник: Слава."""
from fastapi import APIRouter, HTTPException

from app.schemas import (
    HostAction, JoinRequest, JoinResponse, RoomCreated, RoomGuessRequest,
    RoomGuessResponse, RoomState,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", response_model=RoomCreated)
def create_room():
    raise HTTPException(501, "not implemented")


@router.post("/{code}/players", response_model=JoinResponse)
def join(code: str, body: JoinRequest):
    raise HTTPException(501, "not implemented")


@router.post("/{code}/start", response_model=RoomState)
def start(code: str, body: HostAction):
    raise HTTPException(501, "not implemented")


@router.post("/{code}/next", response_model=RoomState)
def next_round(code: str, body: HostAction):
    raise HTTPException(501, "not implemented")


@router.post("/{code}/guess", response_model=RoomGuessResponse)
def guess(code: str, body: RoomGuessRequest):
    raise HTTPException(501, "not implemented")


@router.get("/{code}/state", response_model=RoomState)
def state(code: str, player_id: str | None = None):
    raise HTTPException(501, "not implemented")
