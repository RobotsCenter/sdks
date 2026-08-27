from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RobotsCenterError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(slots=True)
class APIError(RobotsCenterError):
    status: int
    code: str | None = None
    details: Any = None
    request_id: str | None = None


class AuthenticationError(APIError):
    pass


class AuthorizationError(APIError):
    pass


class RateLimitError(APIError):
    retry_after: float | None = None

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class TransportError(RobotsCenterError):
    pass


class PaymentRequiredError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    pass


class ValidationError(APIError):
    pass


class QuotaError(APIError):
    pass


class RealtimeError(RobotsCenterError):
    pass
