"""Доменні помилки. Ігрова логіка кидає їх, а app/main.py перетворює на HTTP-відповідь

    {"error": {"code": "<code>", "message": "<текст>"}}

Повний перелік кодів і статусів є в docs/contract.md (розділ «Помилки»). Змінює лише Слава.
"""


class GameError(Exception):
    status: int = 400
    code: str = "bad_request"

    def __init__(self, message: str | None = None, *, code: str | None = None):
        if code:
            self.code = code
        self.message = message or self.code
        super().__init__(self.message)


class NotFound(GameError):
    status, code = 404, "not_found"


class RegionNotFound(NotFound):
    code = "region_not_found"


class RoundNotFound(NotFound):
    code = "round_not_found"


class RoomNotFound(NotFound):
    code = "room_not_found"


class PlayerNotFound(NotFound):
    code = "player_not_found"


class Forbidden(GameError):
    status, code = 403, "forbidden"


class BadHostKey(Forbidden):
    code = "bad_host_key"


class Conflict(GameError):
    status, code = 409, "conflict"


class InvalidState(Conflict):
    """Дія неможлива в поточному статусі (наприклад, guess у lobby)."""
    code = "invalid_state"


class RoundFinished(Conflict):
    code = "round_finished"


class NoMoreHints(Conflict):
    code = "no_more_hints"


class AlreadyGuessed(Conflict):
    code = "already_guessed"


class NameTaken(Conflict):
    code = "name_taken"


class Unprocessable(GameError):
    status, code = 422, "unprocessable"


class RegionNotPlayable(Unprocessable):
    code = "region_not_playable"


class InvalidName(Unprocessable):
    code = "invalid_name"


class DataUnavailable(GameError):
    """Немає БД або в ній бракує таблиць/даних."""
    status, code = 503, "data_unavailable"
