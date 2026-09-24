"""Unit tests run with the network disabled — the Phase 2 gate's "domain rules
at 100% unit coverage, network disabled". Enforced, not assumed: any attempt
to open a socket or resolve a name fails the test that made it."""

import socket

import pytest


class NetworkDisabled(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise NetworkDisabled("network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
