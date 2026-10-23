"""Outbound HTTP for workflow nodes, guarded against server-side request forgery.

A workflow editor chooses the URLs the HTTP and Slack nodes call, so without a guard any
editor could reach the cloud metadata service, the database or an internal admin panel
from inside the deployment. The guard lives in the network backend, below HTTP:

1. the hostname is resolved once;
2. every resolved address is checked against the blocked ranges below;
3. the TCP connection is opened to a checked address, never to the name again.

Because the socket connects to the address that was checked, DNS rebinding (a second
lookup returning 127.0.0.1) cannot slip through, and TLS still verifies the certificate
against the hostname (SNI). Redirects open new connections through the same backend.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpcore
import httpx

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_EXTRA_BLOCKED = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "100.64.0.0/10",  # carrier-grade NAT, used inside some VPCs
        "192.0.0.0/24",  # IETF protocol assignments
        "198.18.0.0/15",  # benchmarking
        "fd00:ec2::254/128",  # the EC2 metadata service over IPv6
    )
)


class OutboundBlockedError(Exception):
    """The destination resolved to an address workflows may not reach."""


def is_blocked(address: IPAddress) -> bool:
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True
    return any(address in network for network in _EXTRA_BLOCKED)


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    allow_private: bool = False
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def build(cls, allow_private: bool, hosts: Iterable[str]) -> NetworkPolicy:
        return cls(allow_private, frozenset(h.strip().lower() for h in hosts if h.strip()))

    def host_allowed(self, host: str) -> bool:
        return self.allow_private or host.lower().rstrip(".") in self.allowed_hosts


async def resolve(host: str, port: int) -> list[IPAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise httpcore.ConnectError(f"could not resolve {host}: {exc.strerror}") from exc
    addresses: list[IPAddress] = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address not in addresses:
            addresses.append(address)
    return addresses


class GuardedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, policy: NetworkPolicy, inner: httpcore.AsyncNetworkBackend | None = None):
        self._policy = policy
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's backend interface
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        addresses = await resolve(host, port)
        if not self._policy.host_allowed(host):
            for address in addresses:
                if is_blocked(address):
                    raise OutboundBlockedError(
                        f"{host} resolves to {address}, a private or reserved address that "
                        "workflows may not reach. An operator can allow it with "
                        "OUTBOUND_ALLOWED_HOSTS."
                    )
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    str(address),
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError(f"could not connect to {host}:{port}")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's backend interface
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise OutboundBlockedError("unix sockets are not reachable from workflows")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    """httpx's transport with the connection pool swapped for one on the guarded backend.

    `_pool` is the pool attribute httpx has used since 0.18; the unit tests exercise the
    guard through this class, so a rename in httpx fails the suite instead of silently
    removing the protection.
    """

    def __init__(self, policy: NetworkPolicy) -> None:
        super().__init__(retries=0, trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=5.0,
            network_backend=GuardedBackend(policy),
        )


def guarded_client(policy: NetworkPolicy, *, user_agent: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=GuardedTransport(policy),
        headers={"user-agent": user_agent},
        trust_env=False,
        follow_redirects=False,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )
