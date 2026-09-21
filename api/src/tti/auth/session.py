"""Session JWT — HttpOnly, Secure, SameSite=Lax cookie, 12h expiry,
containing only what step 1.3 asks for: the employee id and their
resolved timezone. Name isn't in here on purpose — GET /me re-reads it
from Odoo, see api/src/tti/routes/auth.py."""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

COOKIE_NAME = "tti_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class SessionPayload:
    employee_id: int
    timezone: str


def create_session_jwt(employee_id: int, timezone: str, *, secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"employee_id": employee_id, "timezone": timezone, "iat": now, "exp": now + SESSION_TTL_SECONDS},
        secret,
        algorithm="HS256",
    )


def decode_session_jwt(token: str, *, secret: str) -> SessionPayload:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    return SessionPayload(employee_id=payload["employee_id"], timezone=payload["timezone"])
