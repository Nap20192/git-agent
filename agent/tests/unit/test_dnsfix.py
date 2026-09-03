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


def test_bytes_host_resolves_directly(restore, monkeypatch):
    """httpx/anyio отдаёт host байтами (IDNA): резолвим сами, а не системным."""
    import dns.resolver

    class A:
        def to_text(self):
            return "1.2.3.4"

    monkeypatch.setattr(
        dns.resolver.Resolver,
        "resolve",
        lambda self, name, rtype: [A()] if name == "api.example.com" else [],
    )
    monkeypatch.setattr(
        dnsfix, "_orig_getaddrinfo", lambda *a: (_ for _ in ()).throw(socket.gaierror(-5, "system"))
    )
    dnsfix.install("127.0.0.1")
    for host in (b"api.example.com", "api.example.com."):
        assert socket.getaddrinfo(host, 443, family=0, type=socket.SOCK_STREAM) == [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("1.2.3.4", 443))
        ]
