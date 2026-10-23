"""Match technology signatures against HTTP headers and HTML.

detect() is a pure function: no I/O, so it is easy to unit test.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_SIGNATURES = Path(__file__).with_name("signatures.yaml")
GENERATOR_RE = re.compile(
    r"""<meta[^>]+name=["']generator["'][^>]*content=["']([^"']+)"""
    r"""|<meta[^>]+content=["']([^"']+)["'][^>]*name=["']generator["']""",
    re.IGNORECASE,
)


@dataclass
class Signature:
    name: str
    category: str
    headers: dict[str, re.Pattern] = field(default_factory=dict)
    cookies: list[tuple[str, re.Pattern]] = field(default_factory=list)
    html: list[re.Pattern] = field(default_factory=list)
    meta_generator: re.Pattern | None = None


def _compile(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


def load_signatures(path: Path = DEFAULT_SIGNATURES) -> list[Signature]:
    """Load and pre-compile all signatures once, before scanning pages."""
    signatures = []
    for item in yaml.safe_load(path.read_text()):
        signatures.append(
            Signature(
                name=item["name"],
                category=item["category"],
                headers={k.lower(): _compile(v or "") for k, v in item.get("headers", {}).items()},
                cookies=[(c, _compile(rf"(?:^|[;,]\s*){c}=")) for c in item.get("cookies", [])],
                html=[_compile(p) for p in item.get("html", [])],
                meta_generator=_compile(item["meta_generator"]) if "meta_generator" in item else None,
            )
        )
    return signatures


def extract_generator(html: str) -> str | None:
    match = GENERATOR_RE.search(html)
    return (match.group(1) or match.group(2)) if match else None


def _match(sig: Signature, headers: dict[str, str], set_cookie: str,
           html: str, generator: str | None) -> str | None:
    """Return a short evidence string for the first rule that matches, else None."""
    for name, pattern in sig.headers.items():
        value = headers.get(name)
        if value is not None and pattern.search(value):
            return f"header {name}: {value[:80]}"
    for cookie_name, pattern in sig.cookies:
        if pattern.search(set_cookie):
            return f"cookie {cookie_name}"
    if sig.meta_generator and generator and sig.meta_generator.search(generator):
        return f"meta generator: {generator[:80]}"
    for pattern in sig.html:
        match = pattern.search(html)
        if match:
            return f"html: {match.group(0)[:80]}"
    return None


def detect(signatures: list[Signature], headers: dict[str, str], html: str) -> dict[str, str]:
    """Return {technology name: evidence} for every signature that matches."""
    headers = {k.lower(): v for k, v in headers.items()}
    set_cookie = headers.get("set-cookie", "")
    generator = extract_generator(html)
    found = {}
    for sig in signatures:
        evidence = _match(sig, headers, set_cookie, html, generator)
        if evidence:
            found[sig.name] = evidence
    return found
