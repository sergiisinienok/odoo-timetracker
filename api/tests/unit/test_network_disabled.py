import socket

import pytest

from .conftest import NetworkDisabled


def test_sockets_are_blocked_in_unit_tests():
    with pytest.raises(NetworkDisabled):
        socket.create_connection(("example.com", 80))
    with pytest.raises(NetworkDisabled):
        socket.getaddrinfo("example.com", 80)
    with pytest.raises(NetworkDisabled), socket.socket() as s:
        s.connect(("127.0.0.1", 9))
