"""Draw a stratified, reproducible sample of crawled domains for manual labelling.

The output deliberately hides the detector's results, so labelling stays blind.

Usage:
    uv run python -m mini_technographics.evaluation.make_goldset
"""

import csv
import os
import random
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from mini_technographics.detector.engine import load_signatures

SEED = 42
OUT_DIR = Path("eval")
GOLDSET = OUT_DIR / "goldset.csv"
# (stratum, min detections, max detections or None, sample size)
STRATA = [("none", 0, 0, 10), ("few", 1, 2, 15), ("many", 3, None, 25)]


def write_technology_list(path: Path) -> None:
    """Write the in-scope technology names, grouped by category, for copy-pasting."""
    by_category: dict[str, list[str]] = {}
    for sig in load_signatures():
        by_category.setdefault(sig.category, []).append(sig.name)
    lines = [f"{cat}: " + "; ".join(sorted(names)) for cat, names in sorted(by_category.items())]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    if GOLDSET.exists():
        raise SystemExit(f"{GOLDSET} already exists; refusing to overwrite your labels.")

    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute(
            # One domain per final host: 140 Google domains redirect to www.google.com.
            """SELECT DISTINCT ON (host) id, domain, final_url, n
               FROM (
                   SELECT c.id, c.domain, c.final_url, count(ct.technology_id) AS n,
                          substring(c.final_url from '^https?://([^/:]+)') AS host
                   FROM companies c
                   LEFT JOIN company_technologies ct ON ct.company_id = c.id
                   WHERE c.crawl_status = 'ok'
                   GROUP BY c.id
               ) t
               ORDER BY host, id"""
        ).fetchall()

    rng = random.Random(SEED)
    sample = []
    for _, low, high, size in STRATA:
        pool = [r for r in rows if r[3] >= low and (high is None or r[3] <= high)]
        for company_id, domain, final_url, _n in rng.sample(pool, size):
            sample.append({
                "company_id": company_id,
                "domain": domain,
                "final_url": final_url,
                "true_technologies": "",
                "notes": "",
            })
    rng.shuffle(sample)  # mix the strata so the order gives nothing away

    OUT_DIR.mkdir(exist_ok=True)
    with GOLDSET.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(sample[0]))
        writer.writeheader()
        writer.writerows(sample)
    write_technology_list(OUT_DIR / "technologies.txt")
    print(f"Wrote {len(sample)} domains to {GOLDSET} and the label list to {OUT_DIR}/technologies.txt")


if __name__ == "__main__":
    main()
