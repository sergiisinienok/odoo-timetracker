"""A small fault-injectable HTTP proxy sitting between OdooClient and the
real Odoo instance, for step 2.3's outbox tests.

Only the "uncertain" fault mode needs real proxying: Odoo *processes* the
request for real, then the response is deliberately dropped, simulating
exactly what OdooUncertain exists for — the write happened, the app just
never found out. "Unreachable" doesn't need this proxy at all — tests get
that by pointing OdooClient at a port nothing is listening on.

Deliberately raw asyncio, not a framework: the whole point is precise
control over the TCP-level behavior (read the full request, get the full
real response, then close without writing it), which a request/response
framework doesn't give direct access to.
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class FaultProxy:
    upstream_url: str
    host: str = "127.0.0.1"
    port: int = 0  # 0 = let the OS pick a free port
    eat_next_n_responses: int = 0  # simulate "processed but response lost" for this many requests

    _server: asyncio.AbstractServer | None = field(default=None, init=False, repr=False)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_bytes = await _read_http_message(reader)
            if not request_bytes:
                return

            upstream = urlsplit(self.upstream_url)
            upstream_host = upstream.hostname
            upstream_port = upstream.port or (443 if upstream.scheme == "https" else 80)

            eat_response = self.eat_next_n_responses > 0
            if eat_response:
                self.eat_next_n_responses -= 1

            if upstream.scheme == "https":
                upstream_reader, upstream_writer = await asyncio.open_connection(
                    upstream_host, upstream_port, ssl=ssl.create_default_context()
                )
            else:
                upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, upstream_port)

            try:
                rewritten = _rewrite_host_header(request_bytes, upstream_host, upstream_port, upstream.scheme)
                upstream_writer.write(rewritten)
                await upstream_writer.drain()

                response_bytes = await _read_http_message(upstream_reader)
            finally:
                upstream_writer.close()

            if not eat_response:
                writer.write(response_bytes)
                await writer.drain()
            # else: Odoo processed the request for real (response_bytes
            # proves it completed) — we just never relay it. The client
            # sees the connection close with nothing written back.
        finally:
            writer.close()


async def _read_http_message(reader: asyncio.StreamReader) -> bytes:
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = await reader.read(65536)
        if not chunk:
            break
        head += chunk
    if b"\r\n\r\n" not in head:
        return head

    header_bytes, _, body = head.partition(b"\r\n\r\n")
    content_length = 0
    for line in header_bytes.decode("latin-1").split("\r\n")[1:]:
        key, _, value = line.partition(":")
        if key.strip().lower() == "content-length":
            content_length = int(value.strip())
            break

    while len(body) < content_length:
        chunk = await reader.read(content_length - len(body))
        if not chunk:
            break
        body += chunk

    return header_bytes + b"\r\n\r\n" + body


def _rewrite_host_header(request_bytes: bytes, host: str, port: int, scheme: str) -> bytes:
    header_bytes, sep, body = request_bytes.partition(b"\r\n\r\n")
    lines = header_bytes.split(b"\r\n")
    default_port = 443 if scheme == "https" else 80
    host_value = host.encode() if port == default_port else f"{host}:{port}".encode()

    new_lines = []
    replaced = False
    for line in lines:
        if line.lower().startswith(b"host:"):
            new_lines.append(b"Host: " + host_value)
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.insert(1, b"Host: " + host_value)

    return b"\r\n".join(new_lines) + sep + body
