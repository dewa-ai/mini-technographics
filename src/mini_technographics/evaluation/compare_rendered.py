"""Compare static-crawl detections with detections on the same sites rendered in Chromium.

Both sides use the same detector, so this measures what the static crawl misses
(JavaScript-loaded tags, the 256 KB cap), not whether the signatures are correct.

Usage:
    uv run python -m mini_technographics.evaluation.compare_rendered
"""

import gzip
import os
from collections import Counter
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from mini_technographics.detector.engine import detect, load_signatures

MIN_SUPPORT = 5          # report technologies seen on at least this many rendered pages
SOFT_BLOCK_RATIO = 0.25  # rendered page far smaller than the static one: likely a bot challenge
REPORT = Path("eval/static_vs_rendered.md")


def _html(html_gz: bytes | None) -> str:
    return gzip.decompress(html_gz).decode("utf-8", errors="replace") if html_gz else ""


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def main() -> None:
    load_dotenv()
    signatures = load_signatures()
    category = {s.name: s.category for s in signatures}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            """SELECT c.domain, p.headers, p.html_gz, r.headers, r.html_gz, r.script_urls
               FROM rendered_pages r
               JOIN pages p ON p.company_id = r.company_id
               JOIN companies c ON c.id = r.company_id
               WHERE r.status = 'ok'"""
        ).fetchall()

    static_n: Counter = Counter()
    rendered_n: Counter = Counter()
    both_n: Counter = Counter()
    compared, soft_blocked = 0, []
    for domain, s_headers, s_gz, r_headers, r_gz, scripts in rows:
        static_html, rendered_html = _html(s_gz), _html(r_gz)
        if len(rendered_html) < SOFT_BLOCK_RATIO * len(static_html):
            soft_blocked.append(domain)
            continue
        # Playwright joins repeated headers (e.g. Set-Cookie) with newlines; httpx uses commas.
        r_headers = {k: v.replace("\n", ", ") for k, v in r_headers.items()}
        static = set(detect(signatures, s_headers, static_html))
        rendered = set(detect(signatures, r_headers, rendered_html + "\n" + "\n".join(scripts)))
        static_n.update(static)
        rendered_n.update(rendered)
        both_n.update(static & rendered)
        compared += 1

    total_rendered = sum(rendered_n.values())
    total_both = sum(both_n.values())
    lines = [
        "# Static crawl vs. rendered page",
        "",
        f"- Sites compared: {compared} (excluded as likely soft blocks: {len(soft_blocked)})",
        f"- Detections on rendered pages: {total_rendered}",
        f"- Also found by the static crawl: {total_both} ({_pct(total_both, total_rendered)})",
        f"- Found only by the static crawl: {sum(static_n.values()) - total_both}",
        "",
        "## By category",
        "",
        "| Category | Rendered | Static found | Coverage |",
        "|---|---:|---:|---:|",
    ]
    cat_rendered: Counter = Counter()
    cat_both: Counter = Counter()
    for tech, n in rendered_n.items():
        cat_rendered[category[tech]] += n
        cat_both[category[tech]] += both_n[tech]
    for cat in sorted(cat_rendered, key=lambda c: cat_both[c] / cat_rendered[c]):
        if cat_rendered[cat] >= MIN_SUPPORT:
            lines.append(f"| {cat} | {cat_rendered[cat]} | {cat_both[cat]} | "
                         f"{_pct(cat_both[cat], cat_rendered[cat])} |")

    lines += ["", f"## By technology (seen on at least {MIN_SUPPORT} rendered pages)", "",
              "| Technology | Category | Rendered | Static found | Coverage |",
              "|---|---|---:|---:|---:|"]
    techs = [t for t in rendered_n if rendered_n[t] >= MIN_SUPPORT]
    for tech in sorted(techs, key=lambda t: both_n[t] / rendered_n[t]):
        lines.append(f"| {tech} | {category[tech]} | {rendered_n[tech]} | {both_n[tech]} | "
                     f"{_pct(both_n[tech], rendered_n[tech])} |")
    if soft_blocked:
        lines += ["", "Excluded as likely soft blocks: " + ", ".join(sorted(soft_blocked))]

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nReport written to {REPORT}")


if __name__ == "__main__":
    main()
