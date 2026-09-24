"""No secret in logs or error responses."""

import io
import json
import logging

from tti.logging import JSONFormatter

from .conftest import BASE_URL, ME, SECRETS


def _log_line(monkeypatch, message: str, **extra) -> str:
    for name, value in (
        ("ODOO_KEY", SECRETS["odoo_key"]),
        ("GOOGLE_CLIENT_SECRET", SECRETS["google_client_secret"]),
        ("SESSION_SECRET", SECRETS["session_secret"]),
    ):
        monkeypatch.setenv(name, value)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("secret-test")
    logger.handlers, logger.propagate = [handler], False
    try:
        try:
            raise RuntimeError(f"auth failed with key {SECRETS['odoo_key']}")
        except RuntimeError:
            logger.error(message, exc_info=True, extra=extra)
    finally:
        logger.handlers = []
    return stream.getvalue()


def test_secrets_are_masked_in_message_extra_and_traceback(monkeypatch):
    line = _log_line(
        monkeypatch,
        f"request with {SECRETS['session_secret']}",
        header=f"Bearer {SECRETS['google_client_secret']}",
    )
    for secret in SECRETS.values():
        assert secret not in line
    assert "[redacted]" in line
    json.loads(line)  # still one valid JSON object


async def test_error_responses_carry_no_secret(client, session_cookie):
    responses = [
        await client.get("/entries"),  # 401
        await client.get("/entries", cookies={"tti_session": "junk"}),  # 401
        await client.post("/entries", json={}, headers={"Origin": "https://evil.example"}),  # 403
        await client.delete("/entries/1", cookies=session_cookie, headers={"Origin": BASE_URL}),  # 403 owner
        await client.post("/entries", content=b"x" * 70_000, headers={"Origin": BASE_URL}),  # 413
    ]
    assert {r.status_code for r in responses} >= {401, 403, 413}
    for r in responses:
        for secret in SECRETS.values():
            assert secret not in r.text
        assert "Traceback" not in r.text
