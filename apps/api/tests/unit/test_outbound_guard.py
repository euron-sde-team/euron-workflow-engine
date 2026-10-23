import asyncio
import ipaddress
from collections.abc import AsyncIterator

import httpcore
import pytest

from workflow_engine.integrations import http as guard
from workflow_engine.integrations.http import (
    GuardedBackend,
    NetworkPolicy,
    OutboundBlockedError,
    guarded_client,
    is_blocked,
)

# A public address written as an integer, so no literal public IP sits in the tree.
PUBLIC = ipaddress.ip_address(0x5DB8D822)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "172.16.4.1",
        "192.168.1.20",
        "169.254.169.254",
        "100.64.0.9",
        "::1",
        "fd00::1",
        "::ffff:127.0.0.1",
        "0.0.0.0",  # noqa: S104 - an address under test, nothing binds to it
    ],
)
def test_private_and_reserved_addresses_are_blocked(address: str) -> None:
    assert is_blocked(ipaddress.ip_address(address))


def test_public_addresses_are_allowed() -> None:
    assert not is_blocked(PUBLIC)


class RecordingBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.connected: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[no-untyped-def]  # noqa: ASYNC109
        self.connected.append(host)
        raise httpcore.ConnectError("stop here")

    async def sleep(self, seconds: float) -> None:
        return None


async def test_hostnames_resolving_to_private_addresses_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(
        host: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("169.254.169.254")]

    monkeypatch.setattr(guard, "resolve", fake_resolve)
    inner = RecordingBackend()
    backend = GuardedBackend(NetworkPolicy(), inner)
    with pytest.raises(OutboundBlockedError, match=r"169\.254\.169\.254"):
        await backend.connect_tcp("metadata.example.com", 80)
    assert inner.connected == []


async def test_the_socket_connects_to_the_checked_address_not_the_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(
        host: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [PUBLIC]

    monkeypatch.setattr(guard, "resolve", fake_resolve)
    inner = RecordingBackend()
    with pytest.raises(httpcore.ConnectError):
        await GuardedBackend(NetworkPolicy(), inner).connect_tcp("api.example.com", 443)
    assert inner.connected == [str(PUBLIC)]


async def test_allowed_hosts_may_be_private(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(
        host: str, port: int
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        return [ipaddress.ip_address("172.18.0.5")]

    monkeypatch.setattr(guard, "resolve", fake_resolve)
    inner = RecordingBackend()
    policy = NetworkPolicy.build(False, ["Demo-APIs ", ""])
    with pytest.raises(httpcore.ConnectError):
        await GuardedBackend(policy, inner).connect_tcp("demo-apis", 9131)
    assert inner.connected == ["172.18.0.5"]
    assert policy.allowed_hosts == frozenset({"demo-apis"})


async def test_unix_sockets_are_refused() -> None:
    with pytest.raises(OutboundBlockedError):
        await GuardedBackend(NetworkPolicy()).connect_unix_socket("/var/run/docker.sock")


@pytest.fixture
async def local_server() -> AsyncIterator[int]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield port


async def test_the_real_client_refuses_loopback_unless_allowed(local_server: int) -> None:
    url = f"http://127.0.0.1:{local_server}/"
    async with guarded_client(NetworkPolicy(), user_agent="test") as client:
        with pytest.raises(OutboundBlockedError):
            await client.get(url)
    async with guarded_client(NetworkPolicy(allow_private=True), user_agent="test") as client:
        response = await client.get(url)
    assert response.status_code == 200
    assert response.text == "ok"
