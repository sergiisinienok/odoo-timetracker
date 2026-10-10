"""OdooClient against a fake transport (no network): the 429 and non-JSON
behaviour seen on the trial — see the module docstring in tti/odoo/client.py."""

import asyncio

import httpx
import pytest

from tti.odoo.client import OdooClient
from tti.odoo.errors import OdooUnavailable, OdooUncertain


def _client(handler, **kw) -> OdooClient:
    c = OdooClient("https://odoo.test", "db", "user", "key", transport=httpx.MockTransport(handler), **kw)
    c._uid = 7  # skip authenticate
    return c


def _ok(result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("tti.odoo.client.asyncio.sleep", fake_sleep)
    return waits


async def test_a_429_is_retried_and_then_succeeds(_no_real_sleep):
    calls = iter([httpx.Response(429, text="Too Many Requests"), httpx.Response(429, text=""), _ok([1, 2])])
    client = _client(lambda request: next(calls))
    assert await client.execute_kw("m", "search", []) == [1, 2]
    assert len(_no_real_sleep) == 2


async def test_retry_after_is_honoured_but_capped(_no_real_sleep):
    calls = iter(
        [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(429, headers={"Retry-After": "999"}), _ok(1)]
    )
    await _client(lambda request: next(calls)).execute_kw("m", "x", [])
    assert _no_real_sleep == [2.0, 5.0]


async def test_a_429_that_never_clears_is_unavailable_not_a_crash():
    client = _client(lambda request: httpx.Response(429, text="Too Many Requests"))
    with pytest.raises(OdooUnavailable):
        await client.execute_kw("m", "search", [])


async def test_a_non_json_success_body_is_uncertain_not_a_json_error():
    client = _client(lambda request: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(OdooUncertain):
        await client.execute_kw("m", "create", [{}])


async def test_a_non_json_client_error_is_unavailable():
    client = _client(lambda request: httpx.Response(403, text="<html>forbidden</html>"))
    with pytest.raises(OdooUnavailable):
        await client.execute_kw("m", "search", [])


async def _yield_to_the_loop():
    event = asyncio.Event()
    asyncio.get_running_loop().call_soon(event.set)
    await event.wait()


async def test_calls_in_flight_are_capped():
    in_flight = peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        for _ in range(3):
            await _yield_to_the_loop()  # let the other calls try to start
        in_flight -= 1
        return _ok(1)

    client = _client(handler, max_concurrent_calls=2)
    await asyncio.gather(*(client.execute_kw("m", "x", []) for _ in range(8)))
    assert peak == 2  # concurrent, but never more than the cap
