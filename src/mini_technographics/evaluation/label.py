"""Interactive helper for labelling the gold set faster.

For each unlabelled row it opens the site in your browser, prints the raw
response headers captured at crawl time, and asks for the technologies you
confirmed with Wappalyzer. It never shows the detector's own results.

Usage:
    uv run python -m mini_technographics.evaluation.label

At the prompt:
    names or shortcuts separated by commas, e.g.  cf, gtm, wp, php
    -   the site uses none of the listed technologies
    s   skip this site (unsafe, inappropriate or broken)
    q   save and quit; run again later to continue
    ?   show this help
"""

import csv
import os
import re
import webbrowser

import psycopg
from dotenv import load_dotenv

from mini_technographics.detector.engine import load_signatures
from mini_technographics.evaluation.make_goldset import GOLDSET

ALIASES = {
    "cf": "Cloudflare", "cloudfront": "Amazon CloudFront", "turnstile": "Cloudflare Turnstile",
    "gtm": "Google Tag Manager", "ga": "Google Analytics", "gf": "Google Fonts",
    "fa": "Font Awesome", "wp": "WordPress", "woo": "WooCommerce", "jq": "jQuery",
    "bs": "Bootstrap", "next": "Next.js", "nuxt": "Nuxt.js", "vue": "Vue.js",
    "iis": "Microsoft IIS", "apache": "Apache HTTP Server",
    "adobe": "Adobe Experience Platform Tags", "pixel": "Meta Pixel",
    "recaptcha": "Google reCAPTCHA", "adsense": "Google AdSense", "clarity": "Microsoft Clarity",
}
HEADERS_OF_INTEREST = [
    "server", "via", "x-powered-by", "x-served-by", "x-generator",
    "cf-ray", "x-amz-cf-id", "x-vercel-id", "x-nf-request-id",
]
COOKIE_NAME_RE = re.compile(r"(?:^|,\s*)([\w.\-]+)=")


def load_headers(company_ids: list[int]) -> dict[int, dict[str, str]]:
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            "SELECT company_id, headers FROM pages WHERE company_id = ANY(%s)", (company_ids,)
        ).fetchall()
    return dict(rows)


def show_headers(headers: dict[str, str]) -> None:
    lowered = {k.lower(): v for k, v in headers.items()}
    for name in HEADERS_OF_INTEREST:
        if name in lowered:
            print(f"    {name}: {lowered[name][:100]}")
    cookies = sorted(set(COOKIE_NAME_RE.findall(lowered.get("set-cookie", ""))))
    if cookies:
        print(f"    cookies: {', '.join(cookies)}")


def resolve(token: str, names_lower: dict[str, str]) -> str | None:
    """Map an alias, a full name, or an unambiguous prefix to the official name."""
    t = token.strip().lower()
    if t in ALIASES:
        return ALIASES[t]
    if t in names_lower:
        return names_lower[t]
    matches = [name for low, name in names_lower.items() if low.startswith(t)]
    return matches[0] if len(matches) == 1 else None


def ask(names_lower: dict[str, str]) -> tuple[str, str] | None:
    """Return (technologies, notes), or None if the user wants to quit."""
    while True:
        answer = input("  technologies> ").strip()
        if answer == "q":
            return None
        if answer == "?":
            print(__doc__)
            continue
        if answer == "s":
            return "", "SKIP"
        if answer == "-":
            return "", "none"
        if not answer:
            print("  (type '-' if the site uses none of the listed technologies)")
            continue
        resolved, unknown = [], []
        for token in (t for t in re.split(r"[,;]", answer) if t.strip()):
            name = resolve(token, names_lower)
            if name:
                resolved.append(name)
            else:
                unknown.append(token.strip())
        if unknown:
            print(f"  unknown or ambiguous: {', '.join(unknown)} (see eval/technologies.txt)")
            continue
        labels = "; ".join(sorted(set(resolved)))
        print(f"  = {labels}")
        notes = input("  notes (Enter = none, r = retype)> ").strip()
        if notes == "r":
            continue
        return labels, notes.replace(",", ";")


def save(rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    """Write to a temporary file first, so an interruption never corrupts the CSV."""
    tmp = GOLDSET.with_suffix(".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(GOLDSET)


def main() -> None:
    with GOLDSET.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    names_lower = {s.name.lower(): s.name for s in load_signatures()}
    headers = load_headers([int(r["company_id"]) for r in rows])
    todo = [r for r in rows if not (r["true_technologies"] or r["notes"])]
    start = len(rows) - len(todo)
    print(f"{start}/{len(rows)} already labelled. Type ? for help.\n")

    for n, row in enumerate(todo, start=start + 1):
        print(f"[{n}/{len(rows)}] {row['domain']}  ->  {row['final_url']}")
        show_headers(headers.get(int(row["company_id"]), {}))
        webbrowser.open(row["final_url"])
        result = ask(names_lower)
        if result is None:
            break
        row["true_technologies"], row["notes"] = result
        save(rows, fieldnames)
        print()

    done = sum(1 for r in rows if r["true_technologies"] or r["notes"])
    print(f"Saved. {done}/{len(rows)} labelled.")


if __name__ == "__main__":
    main()
