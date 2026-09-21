from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from tti.auth.errors import AuthError
from tti.auth.google import verify_google_id_token
from tti.auth.session import COOKIE_NAME, SESSION_TTL_SECONDS, SessionPayload, create_session_jwt, decode_session_jwt

router = APIRouter()

_STATE_COOKIE = "tti_oauth_state"
_STATE_COOKIE_TTL_SECONDS = 600


@router.get("/auth/google/login")
async def google_login(request: Request) -> RedirectResponse:
    settings = request.app.state.app_state["settings"]
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{settings.public_base_url}/api/auth/google/callback"

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        # UX hint only, pre-filters Google's account chooser — the hd claim
        # is still verified server-side in auth/google.py regardless.
        "hd": settings.google_hosted_domain,
        "prompt": "select_account",
    }
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    response.set_cookie(
        _STATE_COOKIE, state, max_age=_STATE_COOKIE_TTL_SECONDS, httponly=True, secure=True, samesite="lax"
    )
    return response


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: str, state: str) -> Response:
    settings = request.app.state.app_state["settings"]
    resolver = request.app.state.app_state["employee_resolver"]

    expected_state = request.cookies.get(_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail={"error": "invalid_state"})

    redirect_uri = f"{settings.public_base_url}/api/auth/google/callback"
    async with httpx.AsyncClient(timeout=15.0) as http:
        token_response = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    token_response.raise_for_status()
    id_token_str = token_response.json()["id_token"]

    try:
        identity = await verify_google_id_token(
            id_token_str, client_id=settings.google_client_id, hosted_domain=settings.google_hosted_domain
        )
        resolved = await resolver.resolve(identity.email)
    except AuthError as exc:
        response = JSONResponse(status_code=403, content={"error": exc.code, "message": str(exc)})
        response.delete_cookie(_STATE_COOKIE)
        return response

    session_token = create_session_jwt(resolved.employee_id, resolved.timezone, secret=settings.session_secret)
    response = RedirectResponse(settings.public_base_url)
    response.delete_cookie(_STATE_COOKIE)
    response.set_cookie(
        COOKIE_NAME,
        session_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


async def get_current_session(request: Request) -> SessionPayload:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail={"error": "not_signed_in"})
    settings = request.app.state.app_state["settings"]
    try:
        return decode_session_jwt(token, secret=settings.session_secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail={"error": "invalid_session"}) from exc


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    session = await get_current_session(request)
    odoo = request.app.state.app_state["odoo"]
    [record] = await odoo.execute_kw("hr.employee", "read", [[session.employee_id]], {"fields": ["name"]})
    return {"employee_id": session.employee_id, "name": record["name"], "timezone": session.timezone}
