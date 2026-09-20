"""Minimal reachability check for /healthz.

This is deliberately not the typed client — that's step 1.2
(api/src/tti/odoo/client.py), with the full error taxonomy and connection
pooling. This just answers "is Odoo up, and what version." Confirmed
against the live sandbox by hand: JSON-RPC common.version() returns
{"server_version": "19.0+e", ...}, matching odoo_profile.json.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def get_odoo_version(client: httpx.AsyncClient, odoo_url: str) -> str | None:
    try:
        response = await client.post(
            f"{odoo_url.rstrip('/')}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": "common", "method": "version", "args": []},
                "id": 1,
            },
            timeout=5.0,
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            logger.warning("odoo version check returned an RPC error", extra={"error": body["error"]})
            return None
        return body["result"]["server_version"]
    except httpx.HTTPError:
        logger.warning("odoo unreachable during health check", exc_info=True)
        return None
