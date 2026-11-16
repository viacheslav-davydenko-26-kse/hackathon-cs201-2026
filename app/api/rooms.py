"""/api/rooms (REST + polling раз на 1 с). Власник: Слава."""
from fastapi import APIRouter, Depends, Request

from app import config
from app.deps import get_rooms
from app.game.rooms import RoomManager
from app.schemas import (
    HostAction, JoinRequest, JoinResponse, RoomCreated, RoomGuessRequest, RoomGuessResponse, RoomState,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", response_model=RoomCreated)
def create_room(request: Request, rooms: RoomManager = Depends(get_rooms)):
    """join_url/QR будуються від PUBLIC_URL (якщо задано), інакше від адреси, з якої відкрито host.html."""
    public_url = config.PUBLIC_URL if config.PUBLIC_URL_SET else str(request.base_url)
    return rooms.create_room(public_url)


@router.post("/{code}/players", response_model=JoinResponse, responses={404: {}, 409: {}, 422: {}})
def join(code: str, body: JoinRequest, rooms: RoomManager = Depends(get_rooms)):
    return rooms.join(code.upper(), body.name)


@router.post("/{code}/start", response_model=RoomState, responses={403: {}, 404: {}, 409: {}})
def start(code: str, body: HostAction, rooms: RoomManager = Depends(get_rooms)):
    return rooms.start(code.upper(), body.host_key)


@router.post("/{code}/next", response_model=RoomState, responses={403: {}, 404: {}, 409: {}})
def next_round(code: str, body: HostAction, rooms: RoomManager = Depends(get_rooms)):
    return rooms.next(code.upper(), body.host_key)


@router.post("/{code}/guess", response_model=RoomGuessResponse, responses={404: {}, 409: {}, 422: {}})
def guess(code: str, body: RoomGuessRequest, rooms: RoomManager = Depends(get_rooms)):
    return rooms.guess(code.upper(), body.player_id, body.region_id)


@router.get("/{code}/state", response_model=RoomState, responses={404: {}})
def state(code: str, player_id: str | None = None, rooms: RoomManager = Depends(get_rooms)):
    return rooms.state(code.upper(), player_id)
