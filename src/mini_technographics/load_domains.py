"""Load domains from a Tranco CSV file into the companies table."""

import argparse
import csv
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
from dotenv import load_dotenv

BATCH_SIZE = 1000


def read_domains(path: Path, start: int, limit: int) -> Iterator[str]:
    """Yield domains whose rank is in [start, start + limit)."""
    with path.open(newline="") as f:
        for rank_str, domain in csv.reader(f):
            rank = int(rank_str)
            if rank < start:
                continue
            if rank >= start + limit:
                break
            yield domain.strip().lower()


def count_companies(cur: psycopg.Cursor) -> int:
    cur.execute("SELECT count(*) FROM companies")
    return cur.fetchone()[0]


def insert_batch(cur: psycopg.Cursor, batch: list[tuple[str]]) -> None:
    cur.executemany(
        "INSERT INTO companies (domain) VALUES (%s) ON CONFLICT (domain) DO NOTHING",
        batch,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("data/raw/top-1m.csv"))
    parser.add_argument("--start", type=int, default=1, help="first rank to load")
    parser.add_argument("--limit", type=int, default=10_000, help="number of domains")
    args = parser.parse_args()

    load_dotenv()
    dsn = os.environ["DATABASE_URL"]

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        before = count_companies(cur)
        batch: list[tuple[str]] = []
        for domain in read_domains(args.file, args.start, args.limit):
            batch.append((domain,))
            if len(batch) >= BATCH_SIZE:
                insert_batch(cur, batch)
                batch.clear()
        if batch:
            insert_batch(cur, batch)
        after = count_companies(cur)

    print(f"Inserted {after - before} new domains (total: {after}).")


if __name__ == "__main__":
    main()
