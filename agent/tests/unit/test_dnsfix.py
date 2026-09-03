"""dnsfix: прямой резолвер только для «внешних» имён, фолбэк на системный при неудаче."""

import socket

import pytest

from pkg import dnsfix


@pytest.fixture
def restore():
    orig = socket.getaddrinfo
    yield
    socket.getaddrinfo = orig


def test_install_empty_is_noop(restore):
    before = socket.getaddrinfo
    dnsfix.install("")
    assert socket.getaddrinfo is before


def test_passthrough_and_fallback(restore, monkeypatch):
    calls = []
    monkeypatch.setattr(dnsfix, "_orig_getaddrinfo", lambda *a: (calls.append(a[0]), [("sys",)])[1])
    import dns.resolver

    def nx(*_a, **_k):
        raise dns.resolver.NXDOMAIN

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", nx)  # резолв не удаётся ⇒ фолбэк
    dnsfix.install("127.0.0.1")
    assert socket.getaddrinfo("localhost", 80) == [("sys",)]
    assert socket.getaddrinfo("10.0.0.1", 80) == [("sys",)]
    assert socket.getaddrinfo("api.example.com", 443) == [("sys",)]
    assert calls == ["localhost", "10.0.0.1", "api.example.com"]
