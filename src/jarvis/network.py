from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp.resolver import DefaultResolver


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if not address.is_global:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        embedded = [address.ipv4_mapped, address.sixtofour, *(address.teredo or ())]
        if any(x is not None and not x.is_global for x in embedded):
            return False
        if address in ipaddress.IPv6Network("64:ff9b::/96"):
            return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF).is_global
    return True


def loopback_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or parts.username or parts.password:
        return False
    if parts.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parts.hostname or "").is_loopback
    except ValueError:
        return False


def public_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Only HTTP/HTTPS URLs are allowed.")
    if parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise ValueError("URLs with credentials or a nonstandard port are not allowed.")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal")):
        raise ValueError("The web tool cannot access internal destinations.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not public_address(str(address)):
            raise ValueError("Nonpublic address.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def local_endpoint(url: str) -> str:
    if not loopback_url(url):
        raise ValueError("A local runtime requires a loopback HTTP/HTTPS endpoint.")
    parts = urlsplit(url)
    if parts.hostname == "localhost":
        return urlunsplit(
            parts._replace(netloc="127.0.0.1" + (f":{parts.port}" if parts.port else ""))
        )
    return url


def secure_endpoint(url: str) -> str:
    """Remote credentials and personal data require TLS; loopback can use HTTP."""
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or (parts.scheme != "https" and not loopback_url(url))
    ):
        raise ValueError(
            "Use HTTPS for a remote endpoint, without credentials or fragments in its URL."
        )
    return local_endpoint(url) if loopback_url(url) else url


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        rows = await super().resolve(host, port, family)
        if not rows or any(not public_address(row["host"]) for row in rows):
            raise ValueError("The name resolves to a nonpublic destination.")
        return rows


async def fetch_public(url: str, *, max_bytes=2_000_000, headers=None) -> tuple[str, bytes, str]:
    """DNS is checked in the resolver actually used for the TCP connection, avoiding rebinding.

    Every redirect is revalidated. aiohttp's default connector is never used for this path.
    """
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    timeout = aiohttp.ClientTimeout(total=25, connect=8)
    request_headers = {
        "User-Agent": "JarvisPersonal/0.1 (+local assistant)",
        **(headers or {}),
        "Accept-Encoding": "identity",
    }
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, trust_env=False, auto_decompress=False
    ) as client:
        for _ in range(6):
            url = public_url(url)
            async with client.get(url, headers=request_headers, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    from urllib.parse import urljoin

                    target = urljoin(url, response.headers["Location"])
                    before, after = urlsplit(url), urlsplit(public_url(target))
                    if before.scheme == "https" and after.scheme != "https":
                        raise ValueError("An HTTPS source cannot redirect to unencrypted HTTP.")
                    if (before.scheme, before.hostname, before.port) != (
                        after.scheme,
                        after.hostname,
                        after.port,
                    ):
                        request_headers = {
                            "User-Agent": "JarvisPersonal/0.1 (+local assistant)",
                            "Accept-Encoding": "identity",
                        }
                    url = target
                    continue
                response.raise_for_status()
                if response.headers.get("Content-Encoding", "identity").lower() not in {
                    "",
                    "identity",
                }:
                    raise ValueError("The text reader requires an uncompressed response.")
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > max_bytes:
                        raise ValueError("Document exceeds the size limit.")
                return str(response.url), bytes(chunks), response.headers.get("Content-Type", "")
    raise ValueError("Too many redirects.")
