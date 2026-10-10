"""Fixtures for step 2.8's security tests: the real `tti.main.app` with its
routes and middleware, driven over ASGI with no lifespan (so no live Odoo).
Audit rows go to the real local Postgres, which the audit assertions read."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio

from tti.auth.session import COOKIE_NAME, create_session_jwt
from tti.config import OdooProfile, Settings
from tti.db.session import make_session_factory
from tti.entries.service import EntryService
from tti.main import app
from tti.security.ratelimit import RateLimiter

BASE_URL = "https://tti.example.test"
SECRETS = {
    "odoo_key": "odoo-key-0123456789abcdef",
    "google_client_secret": "google-secret-0123456789",
    "session_secret": "session-secret-0123456789-0123456789",
}
ME = 987001  # an employee id no real employee has
OTHER = 987002


class FakeOdoo:
    """Answers the reads these tests trigger: every account.analytic.line
    belongs to OTHER, and hr.employee reads return a name."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def execute_kw(self, model, method, args, kwargs=None):
        self.calls.append((model, method))
        if (model, method) == ("account.analytic.line", "read"):
            return [
                {
                    "employee_id": [OTHER, "Someone Else"],
                    "date": "2026-09-01",
                    "project_id": [2, "S00001"],
                    "task_id": False,
                    "so_line": False,
                    "is_so_line_edited": False,
                }
            ]
        if (model, method) == ("hr.employee", "read"):
            return [{"id": ME, "name": "Test Employee"}]
        raise AssertionError(f"unexpected odoo call {model}.{method}")

    async def get_version(self) -> str:
        return "19.0"


def _settings() -> Settings:
    return Settings(
        odoo_url="https://odoo.example.test",
        odoo_db="db",
        odoo_user="svc",
        odoo_key=SECRETS["odoo_key"],
        database_url=os.environ["DATABASE_URL"],
        google_client_id="client-id",
        google_client_secret=SECRETS["google_client_secret"],
        google_hosted_domain="example.test",
        session_secret=SECRETS["session_secret"],
        public_base_url=BASE_URL,
        daily_hour_cap=Decimal(10),
        profile_path=Path("/nonexistent"),
    )


@pytest_asyncio.fixture
async def session_factory():
    factory = make_session_factory(os.environ["DATABASE_URL"])
    yield factory
    async with factory() as session:
        from sqlalchemy import text

        await session.execute(text("delete from audit_log where employee_id in (:a, :b)"), {"a": ME, "b": OTHER})
        await session.commit()


@pytest.fixture
def odoo() -> FakeOdoo:
    return FakeOdoo()


@pytest.fixture
def client(session_factory, odoo):
    settings = _settings()
    profile = OdooProfile(
        data={
            "app_entry_id_field": "x_studio_timetracking_app_entry_id",
            "so_line_manual_marker_field": "is_so_line_edited",
        }
    )
    entry_service = EntryService(odoo, profile, MagicMock(), MagicMock(), MagicMock(), settings.daily_hour_cap)
    app.state.app_state = {
        "settings": settings,
        "profile": profile,
        "odoo": odoo,
        "session_factory": session_factory,
        "employee_resolver": MagicMock(),
        "entry_service": entry_service,
    }
    app.state.rate_limiter = RateLimiter()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url=BASE_URL)


@pytest.fixture
def session_cookie() -> dict[str, str]:
    return {COOKIE_NAME: create_session_jwt(ME, "Europe/London", secret=SECRETS["session_secret"])}
