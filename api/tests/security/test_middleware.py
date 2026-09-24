"""Rate limiting, Origin check, CORS, size limit, and error hygiene."""

import httpx
from fastapi import FastAPI

from tti.auth.session import COOKIE_NAME, create_session_jwt
from tti.security.middleware import (
    ANONYMOUS_LIMIT,
    MAX_BODY_BYTES,
    SESSION_LIMIT,
    SESSION_MUTATION_LIMIT,
    install_security,
)
from tti.security.ratelimit import RateLimiter

from .conftest import BASE_URL, ME, OTHER, SECRETS


def _cookie(employee_id: int) -> dict[str, str]:
    return {COOKIE_NAME: create_session_jwt(employee_id, "UTC", secret=SECRETS["session_secret"])}


async def test_rate_limit_is_per_session(client):
    statuses = [(await client.get("/entries", cookies=_cookie(ME))).status_code for _ in range(SESSION_LIMIT + 1)]
    assert 429 not in statuses[:SESSION_LIMIT]
    assert statuses[-1] == 429

    other = await client.get("/entries", cookies=_cookie(OTHER))
    assert other.status_code != 429, "one employee's traffic must not throttle another's"


async def test_429_names_a_retry_time_and_a_clear_message(client):
    for _ in range(SESSION_LIMIT):
        await client.get("/entries", cookies=_cookie(ME))
    r = await client.get("/entries", cookies=_cookie(ME))
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert r.json()["error"] == "rate_limited" and "wait" in r.json()["message"].lower()


async def test_mutations_have_a_tighter_limit(client):
    body = {"assignment_id": "a", "date": "2026-09-01", "hours": 1, "note": ""}
    headers = {"Origin": BASE_URL}
    statuses = [
        (await client.post("/entries", json=body, cookies=_cookie(ME), headers=headers)).status_code
        for _ in range(SESSION_MUTATION_LIMIT + 1)
    ]
    assert statuses[-1] == 429 and 429 not in statuses[:SESSION_MUTATION_LIMIT]


async def test_anonymous_callers_are_limited_by_address(client):
    statuses = [(await client.get("/me")).status_code for _ in range(ANONYMOUS_LIMIT + 1)]
    assert statuses[-1] == 429


async def test_forged_cookie_does_not_earn_a_session_bucket(client):
    """A bad cookie falls back to the per-address limit, so rotating garbage
    session values cannot dodge it."""
    statuses = []
    for i in range(ANONYMOUS_LIMIT + 1):
        statuses.append((await client.get("/me", cookies={COOKIE_NAME: f"garbage-{i}"})).status_code)
    assert statuses[-1] == 429


async def test_foreign_origin_mutation_is_refused(client):
    r = await client.post("/entries", json={}, cookies=_cookie(ME), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


async def test_same_origin_mutation_reaches_the_route(client):
    r = await client.post("/entries", json={}, headers={"Origin": BASE_URL})
    assert r.status_code == 422  # past the Origin check, into request validation


async def test_no_cors_headers_are_ever_emitted(client):
    preflight = await client.options(
        "/entries",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    cross_get = await client.get("/entries", headers={"Origin": "https://evil.example"})
    for r in (preflight, cross_get):
        assert not [h for h in r.headers if h.lower().startswith("access-control-")]


async def test_oversize_body_is_refused(client):
    r = await client.post(
        "/entries", content=b"x" * (MAX_BODY_BYTES + 1), headers={"Origin": BASE_URL, "Content-Type": "application/json"}
    )
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"


async def test_api_responses_are_not_cacheable(client):
    r = await client.get("/me", cookies=_cookie(ME))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


async def test_unhandled_exception_carries_no_stack_trace_or_detail():
    small = FastAPI()
    small.state.app_state = {"settings": None}
    install_security(small, RateLimiter())

    @small.get("/boom")
    async def boom():
        raise RuntimeError("db password is hunter2 at /srv/app/secret.py line 42")

    # Bypass SecurityMiddleware's settings read: exercise only the handler.
    small.user_middleware.clear()
    small.middleware_stack = None
    transport = httpx.ASGITransport(app=small, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"error": "internal_error", "message": "Something went wrong."}
    assert "hunter2" not in r.text and "Traceback" not in r.text and "secret.py" not in r.text


async def test_an_unreachable_odoo_gives_a_plain_503_that_names_no_host(client):
    from tti.main import app
    from tti.odoo.errors import OdooUnavailable

    class Down:
        async def execute_kw(self, *a, **k):
            raise OdooUnavailable("ConnectError: https://odoo.internal.example:8069/jsonrpc refused")

    app.state.app_state["odoo"] = Down()
    r = await client.get("/me", cookies=_cookie(ME))
    assert r.status_code == 503 and r.json()["error"] == "odoo_unavailable"
    assert "odoo.internal.example" not in r.text and "ConnectError" not in r.text
    assert "try again" in r.json()["message"].lower()
