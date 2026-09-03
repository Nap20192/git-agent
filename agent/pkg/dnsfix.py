"""Обход сломанного системного резолвера на dev-машине (зеркало backend/pkg/dnsfix):
при заданном DNS_SERVER имена резолвятся напрямую через него (dnspython), минуя
stub systemd-resolved; IP-литералы, localhost и имена без точки — как обычно;
не разрезолвилось — фолбэк на системный getaddrinfo. Пусто = ничего не делаем.
"""

from __future__ import annotations

import ipaddress
import socket
from functools import cache

_orig_getaddrinfo = socket.getaddrinfo


def _passthrough(host: object) -> bool:
    if not isinstance(host, str) or not host or "." not in host or host == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def install(server: str) -> None:
    if not server:
        return
    import dns.resolver  # dnspython

    host, _, port = server.partition(":")
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [host]
    resolver.port = int(port or 53)
    resolver.lifetime = 5.0
    resolver.cache = dns.resolver.Cache()

    @cache
    def _ips(name: str) -> tuple[str, ...]:
        try:
            return tuple(r.to_text() for r in resolver.resolve(name, "A"))
        except Exception:
            return ()

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if _passthrough(host) or family not in (0, socket.AF_INET):
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        ips = _ips(host.rstrip("."))
        if not ips:
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        socktype = type or socket.SOCK_STREAM
        proto = proto or (
            socket.IPPROTO_UDP if socktype == socket.SOCK_DGRAM else socket.IPPROTO_TCP
        )
        return [(socket.AF_INET, socktype, proto, "", (ip, port or 0)) for ip in ips]

    socket.getaddrinfo = getaddrinfo
