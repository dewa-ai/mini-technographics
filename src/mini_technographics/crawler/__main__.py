"""Crawl homepages for companies with a given crawl_status and store the results.

Usage:
    uv run python -m mini_technographics.crawler --limit 100 --concurrency 30
    uv run python -m mini_technographics.crawler --status timeout   # retry pass
"""

import argparse
import asyncio
import gzip
import os
import time
from collections import Counter

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from mini_technographics.crawler.fetch import FetchResult, fetch_homepage, make_client
from mini_technographics.crawler.robots import is_allowed

WRITE_BATCH = 100
STORE_BODY_STATUSES = {"ok", "http_error", "blocked"}


async def crawl_one(client: httpx.AsyncClient, domain: str) -> FetchResult:
    if not await is_allowed(client, domain):
        return FetchResult(domain, "robots_disallowed")
    return await fetch_homepage(client, domain)


async def worker(client: httpx.AsyncClient, jobs: asyncio.Queue, results: asyncio.Queue) -> None:
    while True:
        company_id, domain = await jobs.get()
        try:
            result = await crawl_one(client, domain)
        except Exception as exc:  # one bad domain must never kill a worker
            result = FetchResult(domain, "error", error=f"{type(exc).__name__}: {exc}"[:200])
        await results.put((company_id, result))
        jobs.task_done()


async def write_batch(conn: psycopg.AsyncConnection, batch: list[tuple[int, FetchResult]]) -> None:
    async with conn.cursor() as cur:
        await cur.executemany(
            """UPDATE companies
               SET crawl_status = %s, final_url = %s, http_status = %s, crawled_at = now()
               WHERE id = %s""",
            [(r.crawl_status, r.final_url, r.http_status, cid) for cid, r in batch],
        )
        pages = [
            (cid, Jsonb(r.headers), gzip.compress(r.body), len(r.body), r.truncated)
            for cid, r in batch
            if r.crawl_status in STORE_BODY_STATUSES
        ]
        if pages:
            await cur.executemany(
                """INSERT INTO pages (company_id, headers, html_gz, html_bytes, truncated)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (company_id) DO UPDATE SET
                       headers = EXCLUDED.headers, html_gz = EXCLUDED.html_gz,
                       html_bytes = EXCLUDED.html_bytes, truncated = EXCLUDED.truncated,
                       fetched_at = now()""",
                pages,
            )
    await conn.commit()  # checkpoint: finished domains survive an interruption


async def writer(conn, results: asyncio.Queue, total: int, stats: Counter, started: float) -> None:
    batch: list[tuple[int, FetchResult]] = []
    done = 0
    while done < total:
        company_id, result = await results.get()
        batch.append((company_id, result))
        stats[result.crawl_status] += 1
        done += 1
        if len(batch) >= WRITE_BATCH or done == total:
            await write_batch(conn, batch)
            batch.clear()
            rate = done / (time.monotonic() - started)
            print(f"  {done}/{total} ({rate:.1f} domains/s) {dict(stats)}", flush=True)


async def run(status: str, limit: int, concurrency: int) -> None:
    load_dotenv()
    async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, domain FROM companies WHERE crawl_status = %s ORDER BY id LIMIT %s",
                (status, limit),
            )
            rows = await cur.fetchall()
            if not rows:
                print(f"No companies with crawl_status = '{status}'.")
                return
            await cur.execute(
                "INSERT INTO crawl_runs (domains_total, notes) VALUES (%s, %s) RETURNING id",
                (len(rows), f"status={status} concurrency={concurrency}"),
            )
            run_id = (await cur.fetchone())[0]
        await conn.commit()

        print(f"Run {run_id}: crawling {len(rows)} domains, concurrency {concurrency}")
        jobs: asyncio.Queue = asyncio.Queue()
        results: asyncio.Queue = asyncio.Queue()
        for row in rows:
            jobs.put_nowait(row)

        stats: Counter = Counter()
        started = time.monotonic()
        async with make_client() as client:
            workers = [asyncio.create_task(worker(client, jobs, results)) for _ in range(concurrency)]
            await writer(conn, results, len(rows), stats, started)
            for task in workers:
                task.cancel()
        elapsed = time.monotonic() - started

        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE crawl_runs
                   SET finished_at = now(), pages_ok = %s, pages_failed = %s,
                       notes = notes || %s
                   WHERE id = %s""",
                (stats["ok"], len(rows) - stats["ok"],
                 f" elapsed={elapsed:.0f}s stats={dict(stats)}", run_id),
            )
        await conn.commit()

    print(f"Finished in {elapsed:.1f}s ({len(rows) / elapsed:.1f} domains/s): {dict(stats)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl company homepages.")
    parser.add_argument("--status", default="pending", help="which crawl_status to (re)crawl")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 100:
        parser.error("--concurrency must be between 1 and 100")
    asyncio.run(run(args.status, args.limit, args.concurrency))


if __name__ == "__main__":
    main()
