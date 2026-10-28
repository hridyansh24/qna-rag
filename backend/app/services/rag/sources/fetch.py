"""
Fetching a syllabus or schedule page by URL, behind the SSRF guard
(docs/design-rag.md §7.1, §9.4).

Every hop resolves its host once, rejects it if any address is loopback,
private, link-local or otherwise not public, then connects to the checked
IP: the request URL carries the IP, the Host header and TLS SNI carry the
real name, so a second DNS answer (rebinding) is never used. Redirects are
followed here, at most MAX_REDIRECTS hops, each checked the same way.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

TIMEOUT_S = 20.0
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
# The compose services' names. They resolve to private addresses, which are
# rejected anyway; naming them makes the intent explicit (§9.4).
INTERNAL_HOSTS = {
    "ollama",
    "infinity",
    "chromadb",
    "mysql",
    "redis",
    "backend",
    "nginx",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
# Some sites refuse httpx's default User-Agent, so say what is asking.
USER_AGENT = "QnA-course-board/1.0 (syllabus and schedule ingestion)"


class FetchError(Exception):
    """A fetch failure whose message is safe to show staff."""


@dataclass(frozen=True)
class FetchedPage:
    url: str  # after redirects: what citations link to
    content: bytes


def address_allowed(ip: str) -> bool:
    """Only global unicast addresses. IPv4-mapped IPv6 is judged as its IPv4."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def resolve(host: str, port: int) -> list[str]:
    """Every address the host resolves to (a seam for tests)."""
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(info[4][0] for info in infos))


async def checked_ip(host: str, port: int) -> str:
    """The first address of `host`, once every address it has is allowed."""
    if host.lower().rstrip(".") in INTERNAL_HOSTS:
        raise FetchError("address not allowed")
    try:
        ips = await resolve(host, port)
    except (socket.gaierror, UnicodeError):
        raise FetchError(f"couldn't resolve {host}")
    if not ips or not all(address_allowed(ip) for ip in ips):
        raise FetchError("address not allowed")
    return ips[0]


def check_url(url: str) -> tuple[str, int]:
    """(host, port) of an http(s) URL with no userinfo; FetchError otherwise."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("only http and https URLs can be fetched")
    if parts.username or parts.password:
        raise FetchError("the URL must not contain a username or password")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise FetchError("the URL's port isn't valid")
    return parts.hostname, port


def _pinned(url: str, ip: str) -> tuple[str, dict[str, str]]:
    """The URL with its host replaced by `ip`, and the Host header for the real name."""
    parts = urlsplit(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = f"{literal}:{parts.port}" if parts.port else literal
    host_header = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), {
        "Host": host_header,
        "User-Agent": USER_AGENT,
    }


async def fetch_page(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> FetchedPage:
    """GET a web page: 20 s per hop, 5 MB cap, at most 5 redirects, each hop checked."""
    async with httpx.AsyncClient(
        timeout=TIMEOUT_S, follow_redirects=False, transport=transport
    ) as client:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            host, port = check_url(current)
            ip = await checked_ip(host, port)
            target, headers = _pinned(current, ip)
            extensions = {"sni_hostname": host} if current.startswith("https") else {}
            try:
                async with client.stream(
                    "GET", target, headers=headers, extensions=extensions
                ) as resp:
                    if resp.status_code in REDIRECT_STATUSES:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError(
                                f"HTTP {resp.status_code} without a Location"
                            )
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        raise FetchError(f"the page returned HTTP {resp.status_code}")
                    return FetchedPage(current.split("#")[0], await _read_capped(resp))
            except httpx.TimeoutException:
                raise FetchError(f"{host} didn't respond within {TIMEOUT_S:.0f} s")
            except httpx.HTTPError as exc:
                raise FetchError(f"couldn't fetch {host}: {type(exc).__name__}")
        raise FetchError(f"more than {MAX_REDIRECTS} redirects")


async def _read_capped(resp: httpx.Response) -> bytes:
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise FetchError("the page is over 5 MB")
    body = bytearray()
    async for chunk in resp.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise FetchError("the page is over 5 MB")
    return bytes(body)
