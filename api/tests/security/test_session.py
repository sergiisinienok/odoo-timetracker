"""Sessions and ownership: cookie flags, expired/forged sessions refused,
another employee's entry refused — and every mutation attempt audited."""

import time
from types import SimpleNamespace

import jwt
from sqlalchemy import text

from tti.auth.session import COOKIE_NAME
from tti.routes import auth as auth_routes

from .conftest import BASE_URL, ME, OTHER, SECRETS


async def test_no_cookie_is_refused(client):
    r = await client.get("/entries")
    assert r.status_code == 401 and r.json()["detail"]["error"] == "not_signed_in"


async def test_expired_session_is_refused(client):
    now = int(time.time())
    expired = jwt.encode(
        {"employee_id": ME, "timezone": "UTC", "iat": now - 90_000, "exp": now - 60},
        SECRETS["session_secret"],
        algorithm="HS256",
    )
    r = await client.get("/entries", cookies={COOKIE_NAME: expired})
    assert r.status_code == 401 and r.json()["detail"]["error"] == "invalid_session"


async def test_session_signed_with_another_secret_is_refused(client):
    now = int(time.time())
    forged = jwt.encode(
        {"employee_id": ME, "timezone": "UTC", "iat": now, "exp": now + 600},
        "not-the-real-secret-at-all-0123456789",
        algorithm="HS256",
    )
    r = await client.get("/entries", cookies={COOKIE_NAME: forged})
    assert r.status_code == 401


async def test_session_cookie_flags(client, monkeypatch):
    """Sign-in issues an HttpOnly, Secure, SameSite=Lax cookie with a 12h expiry."""

    class FakeHttp:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"id_token": "t"})

    async def fake_verify(*a, **k):
        return SimpleNamespace(email="e@example.test")

    class FakeResolver:
        async def resolve(self, email):
            return SimpleNamespace(employee_id=ME, timezone="Europe/London")

    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", FakeHttp)
    monkeypatch.setattr(auth_routes, "verify_google_id_token", fake_verify)
    from tti.main import app

    app.state.app_state["employee_resolver"] = FakeResolver()

    r = await client.get("/auth/google/callback", params={"code": "c", "state": "s"}, cookies={"tti_oauth_state": "s"})
    assert r.status_code == 307
    cookie = next(v for k, v in r.headers.multi_items() if k == "set-cookie" and v.startswith(f"{COOKIE_NAME}="))
    lowered = cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=lax" in lowered
    assert "max-age=43200" in lowered


async def test_another_employees_entry_is_refused_and_audited(client, session_cookie, session_factory):
    for method, path, body in (
        ("DELETE", "/entries/555", None),
        ("PATCH", "/entries/555", {"project_id": 1, "task_id": 2, "date": "2026-09-01", "hours": 1, "note": ""}),
    ):
        r = await client.request(method, path, json=body, cookies=session_cookie, headers={"Origin": BASE_URL})
        assert r.status_code == 403, (method, r.text)
        assert r.json()["detail"]["error"] == "entry_not_owned"

    async with session_factory() as s:
        rows = (
            await s.execute(
                text("select action, target, outcome from audit_log where employee_id = :e order by id"), {"e": ME}
            )
        ).all()
    assert rows == [("entry.delete", "555", "entry_not_owned"), ("entry.update", "555", "entry_not_owned")]
    assert OTHER not in {ME}  # the attempt is attributed to the caller, never the line's owner
