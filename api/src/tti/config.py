"""Env + odoo_profile loading. Code reads `profile.<key>`, never a hardcoded
field or group name — see CLAUDE.md ground rule 2."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT_PROFILE = Path(__file__).resolve().parents[3] / "odoo_profile.json"


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_key: str
    database_url: str
    google_client_id: str
    google_client_secret: str
    google_hosted_domain: str
    session_secret: str
    public_base_url: str
    log_level: str = "INFO"
    profile_path: Path = _REPO_ROOT_PROFILE

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            odoo_url=os.environ["ODOO_URL"],
            odoo_db=os.environ["ODOO_DB"],
            odoo_user=os.environ["ODOO_USER"],
            odoo_key=os.environ["ODOO_KEY"],
            database_url=os.environ["DATABASE_URL"],
            google_client_id=os.environ["GOOGLE_CLIENT_ID"],
            google_client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            google_hosted_domain=os.environ["GOOGLE_HOSTED_DOMAIN"],
            session_secret=os.environ["SESSION_SECRET"],
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            profile_path=Path(os.environ.get("ODOO_PROFILE_PATH", str(_REPO_ROOT_PROFILE))),
        )


@dataclass(frozen=True)
class OdooProfile:
    """Odoo facts, sourced only from odoo_profile.json — never hardcoded.
    See CLAUDE.md ground rule 2."""

    data: dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        try:
            return self.data[name]
        except KeyError as exc:
            raise AttributeError(f"odoo_profile.json has no key {name!r}") from exc

    @property
    def odoo_version(self) -> str | None:
        return self.data.get("odoo_version")

    @classmethod
    def load(cls, path: Path) -> "OdooProfile | None":
        try:
            with path.open() as f:
                return cls(data=json.load(f))
        except FileNotFoundError:
            return None
