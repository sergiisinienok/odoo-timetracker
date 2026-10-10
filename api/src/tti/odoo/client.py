"""One typed, async, well-behaved way to talk to Odoo.

Error shapes confirmed by hand against the live sandbox before writing this
mapping (CLAUDE.md ground rule 1):
  - Bad credentials to common.authenticate() come back as a plain falsy
    `result`, not a JSON-RPC error.
  - Every other rejection (unknown model, unknown method, AccessDenied,
    AccessError, ValidationError, ...) comes back HTTP 200 with a top-level
    "error" object and error.data.name naming the Odoo exception class.
    Odoo has already fully received and processed the call by the time this
    happens, so all of these map to OdooRejected regardless of which
    exception class raised it — there is no ambiguity about the outcome.
  - Odoo Online rate-limits with HTTP 429 and a body that is not JSON (seen on
    the trial under a page load's burst of requests). A 429 means the call was
    not processed, so it is always safe to retry; after a few tries it is
    reported as OdooUnavailable. A body that is not JSON is never allowed to
    escape as a JSONDecodeError.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import TracebackType
from typing import Any, Self

import httpx

from tti.odoo.errors import OdooRejected, OdooUnavailable, OdooUncertain

logger = logging.getLogger(__name__)


# 429 handling: how many times to retry, and the longest we will wait for one.
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_DEFAULT_WAIT_S = 1.0
_RATE_LIMIT_MAX_WAIT_S = 5.0
# Calls in flight at once. A page load fans out into several requests and the
# catalog into several Odoo calls; Odoo Online answers a burst with 429s.
_MAX_CONCURRENT_CALLS = 3


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    try:
        wait = float(response.headers.get("Retry-After", ""))
    except ValueError:
        wait = _RATE_LIMIT_DEFAULT_WAIT_S * 2**attempt
    return min(max(wait, 0.0), _RATE_LIMIT_MAX_WAIT_S)


class OdooClient:
    def __init__(
        self,
        url: str,
        db: str,
        user: str,
        api_key: str,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_concurrent_calls: int = _MAX_CONCURRENT_CALLS,
    ) -> None:
        self._db = db
        self._user = user
        self._key = api_key
        self._jsonrpc_url = f"{url.rstrip('/')}/jsonrpc"
        self._http = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._in_flight = asyncio.Semaphore(max_concurrent_calls)
        self._uid: int | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def authenticate(self) -> int:
        result = await self._call("common", "authenticate", [self._db, self._user, self._key, {}])
        if not result:
            raise OdooRejected("Odoo authentication failed — check ODOO_USER/ODOO_KEY")
        self._uid = result
        return self._uid

    async def get_version(self) -> str:
        result = await self._call("common", "version", [])
        return result["server_version"]

    async def execute_kw(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
        """The single primitive; everything else that talks to a model is
        built on this."""
        if self._uid is None:
            await self.authenticate()

        try:
            return await self._call(
                "object", "execute_kw", [self._db, self._uid, self._key, model, method, args, kwargs or {}]
            )
        except OdooRejected as exc:
            if exc.odoo_exception != "odoo.exceptions.AccessDenied":
                raise
            # The cached uid may have gone stale (key rotated, user
            # deactivated) — re-authenticate once and retry, rather than
            # trusting a session that was fine a moment ago.
            self._uid = None
            await self.authenticate()
            return await self._call(
                "object", "execute_kw", [self._db, self._uid, self._key, model, method, args, kwargs or {}]
            )

    async def _call(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        start = time.monotonic()
        outcome = "error"
        try:
            response = await self._post_with_rate_limit_retry(service, method, payload)

            if response.status_code >= 500:
                outcome = "unavailable"
                raise OdooUnavailable(f"Odoo returned {response.status_code} calling {service}.{method}")

            try:
                body = response.json()
            except ValueError as exc:
                # Not JSON. On a success status the call may well have been
                # processed, so the outcome is unknown; otherwise Odoo (or a
                # proxy in front of it) refused before processing anything.
                if response.status_code < 400:
                    outcome = "uncertain"
                    raise OdooUncertain(f"Odoo sent an unreadable response calling {service}.{method}") from exc
                outcome = "unavailable"
                raise OdooUnavailable(f"Odoo returned {response.status_code} calling {service}.{method}") from exc

            if "error" in body:
                error = body["error"]
                data = error.get("data", {})
                outcome = "rejected"
                raise OdooRejected(
                    data.get("message", error.get("message", "Odoo rejected the call")),
                    odoo_exception=data.get("name"),
                )

            outcome = "ok"
            return body["result"]
        except OdooUnavailable:
            outcome = "unavailable"
            raise
        finally:
            logger.info(
                "odoo rpc call",
                extra={
                    "service": service,
                    "method": method,
                    "duration_s": round(time.monotonic() - start, 3),
                    "outcome": outcome,
                },
            )

    async def _post_with_rate_limit_retry(self, service: str, method: str, payload: dict[str, Any]) -> httpx.Response:
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                async with self._in_flight:
                    response = await self._http.post(self._jsonrpc_url, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.WriteTimeout) as exc:
                raise OdooUnavailable(f"Odoo unreachable calling {service}.{method}: {exc}") from exc
            except (httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                raise OdooUncertain(f"Odoo response uncertain calling {service}.{method}: {exc}") from exc

            if response.status_code != 429:
                return response
            if attempt == _RATE_LIMIT_RETRIES:
                raise OdooUnavailable(f"Odoo rate-limited calling {service}.{method} (HTTP 429)")
            wait = _retry_after_seconds(response, attempt)
            logger.warning(
                "odoo rate limit (429) — retrying",
                extra={"service": service, "method": method, "wait_s": wait, "attempt": attempt + 1},
            )
            await asyncio.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover
