"""Run technology detection over crawled pages and store the results.

Usage:
    uv run python -m mini_technographics.detector
"""

import gzip
import os
import time
from collections import Counter

import psycopg
from dotenv import load_dotenv

from mini_technographics.detector.engine import Signature, detect, load_signatures

READ_BATCH = 200


def sync_technologies(conn: psycopg.Connection, signatures: list[Signature]) -> dict[str, int]:
    """Upsert every signature into the technologies table and return {name: id}."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO technologies (name, category) VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE SET category = EXCLUDED.category""",
            [(s.name, s.category) for s in signatures],
        )
        cur.execute("SELECT name, id FROM technologies")
        ids = dict(cur.fetchall())
    conn.commit()
    return ids


def save_batch(conn: psycopg.Connection, batch: list[tuple[int, int, str]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO company_technologies (company_id, technology_id, evidence)
               VALUES (%s, %s, %s)
               ON CONFLICT (company_id, technology_id) DO UPDATE
               SET last_seen = now(), evidence = EXCLUDED.evidence""",
            batch,
        )
    conn.commit()


def main() -> None:
    load_dotenv()
    dsn = os.environ["DATABASE_URL"]
    signatures = load_signatures()
    started = time.monotonic()
    pages = pages_with_detections = 0
    counts: Counter = Counter()

    # Two connections: a server-side cursor streams pages on one, writes commit on the other.
    with psycopg.connect(dsn) as read_conn, psycopg.connect(dsn) as write_conn:
        tech_ids = sync_technologies(write_conn, signatures)
        with read_conn.cursor(name="pages_stream") as read_cur:
            read_cur.itersize = READ_BATCH
            # Only successful crawls: error and challenge pages would produce misleading detections.
            read_cur.execute(
                """SELECT p.company_id, p.headers, p.html_gz
                   FROM pages p JOIN companies c ON c.id = p.company_id
                   WHERE c.crawl_status = 'ok' ORDER BY p.company_id"""
            )
            while rows := read_cur.fetchmany(READ_BATCH):
                batch = []
                for company_id, headers, html_gz in rows:
                    html = gzip.decompress(html_gz).decode("utf-8", errors="replace") if html_gz else ""
                    found = detect(signatures, headers, html)
                    pages += 1
                    pages_with_detections += bool(found)
                    for name, evidence in found.items():
                        counts[name] += 1
                        batch.append((company_id, tech_ids[name], evidence))
                if batch:
                    save_batch(write_conn, batch)
                print(f"  {pages} pages scanned", flush=True)

    elapsed = time.monotonic() - started
    print(f"\nScanned {pages} pages in {elapsed:.1f}s ({pages / elapsed:.0f} pages/s)")
    print(f"Pages with at least one detection: {pages_with_detections} "
          f"({100 * pages_with_detections / max(pages, 1):.1f}%)")
    print(f"Total detections: {sum(counts.values())}\n\nTop 15 technologies:")
    for name, n in counts.most_common(15):
        print(f"  {name:32} {n:5}  ({100 * n / max(pages, 1):.1f}%)")


if __name__ == "__main__":
    main()
