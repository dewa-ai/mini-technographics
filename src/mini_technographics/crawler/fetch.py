"""Fetch a single homepage with strict timeouts and a size cap."""

import socket
from dataclasses import dataclass, field

import httpx

USER_AGENT = "mini-technographics/0.1 (+https://github.com/dewa-ai/mini-technographics)"
MAX_BYTES = 256 * 1024  # most technology signatures live in headers and <head>
TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=5.0)
BLOCKED_STATUSES = {401, 403, 429}
# Hosts that national or ISP filters redirect blocked sites to
# (observed while crawling from an Indonesian network).
BLOCK_PAGE_HOSTS = {"internet-positif.info"}


@dataclass
class FetchResult:
    domain: str
    crawl_status: str  # ok | dns_failed | timeout | http_error | blocked | error
    final_url: str | None = None
    http_status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    truncated: bool = False
    error: str | None = None


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=True,
        max_redirects=10,
    )


def _is_dns_error(exc: BaseException) -> bool:
    """Walk the exception chain looking for a DNS resolution failure."""
    current: BaseException | None = exc
    for _ in range(10):
        if current is None:
            return False
        if isinstance(current, socket.gaierror):
            return True
        current = current.__cause__ or current.__context__
    return False


def _classify_status(status: int) -> str:
    if status in BLOCKED_STATUSES:
        return "blocked"
    if status >= 400:
        return "http_error"
    return "ok"


def _classify_response(response: httpx.Response) -> str:
    if response.url.host in BLOCK_PAGE_HOSTS:
        return "isp_blocked"
    return _classify_status(response.status_code)


async def _read_capped(response: httpx.Response) -> tuple[bytes, bool]:
    """Read the body but stop after MAX_BYTES."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BYTES:
            return b"".join(chunks)[:MAX_BYTES], True
    return b"".join(chunks), False


async def fetch_homepage(client: httpx.AsyncClient, domain: str) -> FetchResult:
    """Try HTTPS first, then fall back to HTTP on connection errors."""
    last_error: Exception | None = None
    for scheme in ("https", "http"):
        try:
            async with client.stream("GET", f"{scheme}://{domain}/") as response:
                body, truncated = await _read_capped(response)
                return FetchResult(
                    domain=domain,
                    crawl_status=_classify_response(response),
                    final_url=str(response.url),
                    http_status=response.status_code,
                    headers=dict(response.headers),
                    body=body,
                    truncated=truncated,
                )
        except httpx.TimeoutException as exc:
            return FetchResult(domain, "timeout", error=type(exc).__name__)
        except httpx.ConnectError as exc:
            if _is_dns_error(exc):
                return FetchResult(domain, "dns_failed", error=str(exc)[:200])
            last_error = exc  # e.g. TLS failure on HTTPS: try plain HTTP next
        except httpx.HTTPError as exc:
            last_error = exc
    return FetchResult(domain, "error", error=f"{type(last_error).__name__}: {last_error}"[:200])
