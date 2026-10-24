from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp.resolver import DefaultResolver


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
        raise ValueError("Sono ammessi soltanto URL HTTP/HTTPS.")
    if parts.username or parts.password or parts.port not in {None, 80, 443}:
        raise ValueError("URL con credenziali o porta non standard non ammesso.")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal")):
        raise ValueError("Destinazione interna non ammessa al tool web.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Indirizzo non pubblico.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


class PublicResolver(DefaultResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        rows = await super().resolve(host, port, family)
        if not rows or any(not ipaddress.ip_address(row["host"]).is_global for row in rows):
            raise ValueError("Il nome risolve a una destinazione non pubblica.")
        return rows


async def fetch_public(url: str, *, max_bytes=2_000_000, headers=None) -> tuple[str, bytes, str]:
    """DNS is checked in the resolver actually used for the TCP connection, avoiding rebinding.

    Every redirect is revalidated. aiohttp's default connector is never used for this path.
    """
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    timeout = aiohttp.ClientTimeout(total=25, connect=8)
    request_headers = {"User-Agent": "JarvisPersonal/0.1 (+local assistant)", **(headers or {})}
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, trust_env=False
    ) as client:
        for _ in range(6):
            url = public_url(url)
            async with client.get(url, headers=request_headers, allow_redirects=False) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    from urllib.parse import urljoin

                    url = urljoin(url, response.headers["Location"])
                    continue
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > max_bytes:
                        raise ValueError("Documento oltre il limite di dimensione.")
                return str(response.url), bytes(chunks), response.headers.get("Content-Type", "")
    raise ValueError("Troppi reindirizzamenti.")
