"""Google ID token verification. `verify_google_id_token` is the boundary
unit tests mock — see api/tests/unit/test_auth.py — everything on this side
of it (the hd and email_verified checks) is ours and gets exercised for
real; everything on the other side (signature/issuer/audience checks) is
google-auth's job, not re-implemented here."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from tti.auth.errors import ForeignDomainRejected, UnverifiedEmailRejected

_google_request = google_requests.Request()


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    name: str
    hosted_domain: str | None


async def verify_google_id_token(token: str, *, client_id: str, hosted_domain: str) -> GoogleIdentity:
    # verify_oauth2_token is sync and fetches/caches Google's public certs
    # over the network — keep it off the event loop.
    payload = await asyncio.to_thread(google_id_token.verify_oauth2_token, token, _google_request, client_id)

    if not payload.get("email_verified", False):
        raise UnverifiedEmailRejected("Google account email is not verified")

    hd = payload.get("hd")
    if hd != hosted_domain:
        raise ForeignDomainRejected(f"hd claim {hd!r} does not match required domain {hosted_domain!r}")

    return GoogleIdentity(email=payload["email"], name=payload.get("name", payload["email"]), hosted_domain=hd)
