"""Render a sample of crawled sites in headless Chromium.

Used for the static-vs-rendered evaluation. Runs inside Docker (Dockerfile.render);
results are stored in the rendered_pages table. Safe to re-run: finished sites are skipped.

Usage:
    docker compose --profile render run --rm renderer --sample 200
"""

import argparse
import asyncio
import gzip
import os
import random

import psycopg
from playwright.async_api import Browser, Request, async_playwright
from psycopg.types.json import Jsonb

SEED = 42
CONCURRENCY = 4
NAV_TIMEOUT_MS = 20_000
# 'load' never fired within the timeout on ~12% of heavy pages (ads, long polling),
# so wait for DOMContentLoaded, then give tag managers time to load their scripts.
SETTLE_MS = 3_000
USER_AGENT = "mini-technographics/0.1 (+https://github.com/dewa-ai/mini-technographics)"


def pick_sample(conn: psycopg.Connection, size: int) -> list[tuple[int, str]]:
    """Same seeded sample on every run, one site per final host, minus finished ones."""
    rows = conn.execute(
        """SELECT DISTINCT ON (host) id, final_url
           FROM (SELECT id, final_url, substring(final_url from '^https?://([^/:]+)') AS host
                 FROM companies WHERE crawl_status = 'ok') t
           ORDER BY host, id"""
    ).fetchall()
    sample = random.Random(SEED).sample(rows, min(size, len(rows)))
    done = {r[0] for r in conn.execute("SELECT company_id FROM rendered_pages").fetchall()}
    return [r for r in sample if r[0] not in done]


async def render_one(browser: Browser, url: str) -> tuple[str, dict, str, list[str], str | None]:
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    scripts: list[str] = []

    def on_request(request: Request) -> None:
        if request.resource_type == "script":
            scripts.append(request.url)

    page.on("request", on_request)
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await page.wait_for_timeout(SETTLE_MS)
        headers = await response.all_headers() if response else {}
        # goto() does not raise on 4xx/5xx, so record the HTTP status explicitly
        status = "ok" if response is None or response.status < 400 else f"http_{response.status}"
        return status, headers, await page.content(), scripts, None
    except Exception as exc:  # noqa: BLE001 - record the failure and move on
        return "error", {}, "", scripts, f"{type(exc).__name__}: {exc}"[:200]
    finally:
        await context.close()


async def run(size: int) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        sample = pick_sample(conn, size)
        print(f"Rendering {len(sample)} sites, concurrency {CONCURRENCY}", flush=True)
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async with async_playwright() as p:
            browser = await p.chromium.launch()

            async def guarded(company_id: int, url: str):
                async with semaphore:
                    return company_id, await render_one(browser, url)

            tasks = [asyncio.create_task(guarded(cid, url)) for cid, url in sample]
            for n, task in enumerate(asyncio.as_completed(tasks), start=1):
                company_id, (status, headers, html, scripts, error) = await task
                conn.execute(
                    """INSERT INTO rendered_pages
                           (company_id, status, headers, html_gz, script_urls, error)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (company_id) DO UPDATE SET
                           status = EXCLUDED.status, headers = EXCLUDED.headers,
                           html_gz = EXCLUDED.html_gz, script_urls = EXCLUDED.script_urls,
                           error = EXCLUDED.error, rendered_at = now()""",
                    (company_id, status, Jsonb(headers), gzip.compress(html.encode()),
                     Jsonb(scripts), error),
                )
                conn.commit()
                print(f"  {n}/{len(sample)} {status} ({len(scripts)} scripts)", flush=True)
            await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Render sampled sites in headless Chromium.")
    parser.add_argument("--sample", type=int, default=200)
    asyncio.run(run(parser.parse_args().sample))


if __name__ == "__main__":
    main()
