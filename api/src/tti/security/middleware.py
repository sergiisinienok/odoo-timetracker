"""Request-level defences — step 2.8. Order matters: cheapest and most
absolute first (size, origin), then the rate limit, which needs to identify
the caller.

CORS is deliberately absent, not misconfigured: the web app and the api share
one origin behind Caddy, so no cross-origin read is ever legitimate. With no
CORS middleware the api never emits Access-Control-Allow-*, and browsers block
cross-origin reads of it. The Origin check below closes the write side: a
cross-site form post carries the session cookie (SameSite=Lax permits
top-level navigations) but also carries a foreign Origin, and is refused.
"""

from __future__ import annotations

import jwt
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from tti.auth.session import COOKIE_NAME, decode_session_jwt
from tti.security.ratelimit import RateLimiter

MAX_BODY_BYTES = 64 * 1024

SESSION_LIMIT = 120  # requests per minute, any method
SESSION_MUTATION_LIMIT = 30  # per minute, POST/PATCH/DELETE
ANONYMOUS_LIMIT = 30  # per minute per client address (sign-in flow, probes)
WINDOW_SECONDS = 60.0

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_UNMETERED_PATHS = {"/healthz", "/readyz"}


def _client_address(request: Request) -> str:
    # Caddy replaces X-Forwarded-For with the real peer; the api port is not
    # published, so a caller cannot reach it without going through Caddy.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _reject(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message}, headers=headers)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _UNMETERED_PATHS:
            return await call_next(request)

        app_state = request.app.state.app_state
        settings = app_state["settings"]
        mutating = request.method not in _SAFE_METHODS

        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
            return _reject(413, "payload_too_large", "Request body is too large.")

        if mutating:
            origin = request.headers.get("origin")
            if origin is not None and origin.rstrip("/") != settings.public_base_url.rstrip("/"):
                return _reject(403, "bad_origin", "Cross-origin requests are not allowed.")

        limiter: RateLimiter = request.app.state.rate_limiter
        retry_after = self._check_rate(limiter, request, settings.session_secret, mutating)
        if retry_after is not None:
            return _reject(
                429,
                "rate_limited",
                "Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
            )

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _check_rate(limiter: RateLimiter, request: Request, secret: str, mutating: bool) -> float | None:
        token = request.cookies.get(COOKIE_NAME)
        employee_id: int | None = None
        if token is not None:
            try:
                employee_id = decode_session_jwt(token, secret=secret).employee_id
            except jwt.PyJWTError:
                employee_id = None  # a bad cookie earns no session bucket

        if employee_id is None:
            return limiter.check(("ip", _client_address(request)), limit=ANONYMOUS_LIMIT, window_seconds=WINDOW_SECONDS)

        if mutating:
            wait = limiter.check(
                ("session-mutation", employee_id), limit=SESSION_MUTATION_LIMIT, window_seconds=WINDOW_SECONDS
            )
            if wait is not None:
                return wait
        return limiter.check(("session", employee_id), limit=SESSION_LIMIT, window_seconds=WINDOW_SECONDS)


def install_security(app: FastAPI, limiter: RateLimiter | None = None) -> None:
    app.state.rate_limiter = limiter or RateLimiter()
    app.add_middleware(SecurityMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # No exception text, no traceback: those go to the log, not the caller.
        import logging

        logging.getLogger(__name__).error("unhandled exception", exc_info=exc, extra={"path": request.url.path})
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Something went wrong."})
