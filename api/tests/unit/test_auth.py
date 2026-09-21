import jwt as pyjwt
import pytest

import tti.auth.google as google_module
from tti.auth.errors import ForeignDomainRejected, UnverifiedEmailRejected
from tti.auth.google import verify_google_id_token
from tti.auth.session import create_session_jwt, decode_session_jwt


def _patch_verify(monkeypatch, payload):
    monkeypatch.setattr(google_module.google_id_token, "verify_oauth2_token", lambda *a, **kw: payload)


async def test_foreign_hd_is_refused(monkeypatch):
    _patch_verify(
        monkeypatch,
        {"email": "someone@example.com", "email_verified": True, "hd": "example.com", "name": "Someone"},
    )
    with pytest.raises(ForeignDomainRejected):
        await verify_google_id_token("fake-token", client_id="client", hosted_domain="particlesglobal.com")


async def test_personal_account_with_no_hd_claim_is_refused(monkeypatch):
    _patch_verify(monkeypatch, {"email": "someone@gmail.com", "email_verified": True, "name": "Someone"})
    with pytest.raises(ForeignDomainRejected):
        await verify_google_id_token("fake-token", client_id="client", hosted_domain="particlesglobal.com")


async def test_unverified_email_is_refused(monkeypatch):
    _patch_verify(
        monkeypatch,
        {"email": "person@particlesglobal.com", "email_verified": False, "hd": "particlesglobal.com"},
    )
    with pytest.raises(UnverifiedEmailRejected):
        await verify_google_id_token("fake-token", client_id="client", hosted_domain="particlesglobal.com")


async def test_valid_domain_token_is_accepted(monkeypatch):
    _patch_verify(
        monkeypatch,
        {
            "email": "s.sinienok@particlesglobal.com",
            "email_verified": True,
            "hd": "particlesglobal.com",
            "name": "Sergii Sinienok",
        },
    )
    identity = await verify_google_id_token("fake-token", client_id="client", hosted_domain="particlesglobal.com")
    assert identity.email == "s.sinienok@particlesglobal.com"
    assert identity.hosted_domain == "particlesglobal.com"


_TEST_SECRET = "test-secret-0123456789abcdef0123456789"  # 32+ bytes, avoids jwt's InsecureKeyLengthWarning
_OTHER_SECRET = "other-secret-0123456789abcdef0123456789"


def test_session_jwt_round_trip():
    token = create_session_jwt(42, "Europe/Lisbon", secret=_TEST_SECRET)
    payload = decode_session_jwt(token, secret=_TEST_SECRET)
    assert payload.employee_id == 42
    assert payload.timezone == "Europe/Lisbon"


def test_session_jwt_rejects_wrong_secret():
    token = create_session_jwt(42, "Europe/Lisbon", secret=_TEST_SECRET)
    with pytest.raises(pyjwt.PyJWTError):
        decode_session_jwt(token, secret=_OTHER_SECRET)
