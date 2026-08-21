from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def public_test_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep HTTP unit tests independent from the host's DNS resolver."""
    original_getaddrinfo = socket.getaddrinfo

    def stable_getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(host).rstrip(".").lower() in {"example.com", "new-url.com"}:
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", port),
                )
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", stable_getaddrinfo)
