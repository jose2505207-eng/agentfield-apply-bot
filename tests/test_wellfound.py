"""
Tests for WellfoundAdapter — parser unit tests (no HTTP calls) + live smoke.

Parser tests use the real HTML captured from a live fetch so they catch
regressions if Wellfound changes their card structure.

Run:
  python -m tests.test_wellfound            # parser tests only (no HTTP)
  LIVE=1 python -m tests.test_wellfound     # also hits Bright Data API
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.jobs.wellfound import WellfoundAdapter

# ---------------------------------------------------------------------------
# Minimal realistic HTML snippets for parser unit tests.
# Copied from the actual Wellfound search page structure (May 2026).
# ---------------------------------------------------------------------------

CARD_REMOTE = """
<div class="mb-2 flex flex-col">
  <div class="flex flex-row">
    <div class="ml-4 flex-1">
      <div class="mb-1">
        <a class="styles_component__UCLp3" href="/jobs/4206775-servicenow-osm-expert">
          ServiceNow Expert
        </a>
      </div>
      <div class="text-sm">
        <span>Four Dragons<!-- --> • </span>
        <span class="text-gray-700">Remote only<!-- --> •<!-- --> <!-- -->$180k – $200k • 0.1% • <!-- -->today</span>
      </div>
    </div>
  </div>
</div>
"""

CARD_OFFICE = """
<div class="mb-2">
  <div class="ml-4 flex-1">
    <div class="mb-1">
      <a href="/jobs/4206749-kernel-engineer-scientific-computing-spu">
        Kernel Engineer — Scientific Computing (SPU)
      </a>
    </div>
    <div class="text-sm">
      <span>Vorticity<!-- --> • </span>
      <span class="text-gray-700">Redwood City<!-- --> •<!-- --> <!-- -->$120k – $170k • 0.25% – 0.5% • <!-- -->today</span>
    </div>
  </div>
</div>
"""

CARD_NO_SALARY = """
<div class="mb-2">
  <div class="ml-4 flex-1">
    <div class="mb-1">
      <a href="/jobs/9999999-senior-designer">
        Senior Designer
      </a>
    </div>
    <div class="text-sm">
      <span>Acme<!-- --> • </span>
      <span class="text-gray-700">New York<!-- --> • <!-- -->2 days ago</span>
    </div>
  </div>
</div>
"""

# Combine into one fake search-results page
FAKE_HTML = CARD_REMOTE + CARD_OFFICE + CARD_NO_SALARY


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

PASS = FAIL = 0


def _ok(label: str) -> None:
    global PASS; PASS += 1
    print(f"  ✅ {label}")


def _fail(label: str, reason: str) -> None:
    global FAIL; FAIL += 1
    print(f"  ❌ {label}\n        {reason}")


def _check(label: str, cond: bool, reason: str = "") -> None:
    (_ok if cond else lambda l: _fail(l, reason or "assertion failed"))(label)


# ---------------------------------------------------------------------------
# Parser unit tests (no HTTP)
# ---------------------------------------------------------------------------


def test_parser_extracts_title_company_salary():
    print("\n[test] parser: title, company, salary from card HTML")
    adapter = WellfoundAdapter(api_token="dummy", zone="dummy")
    jobs = adapter._parse(FAKE_HTML, max_results=10)

    _check("returns 3 jobs", len(jobs) == 3, f"got {len(jobs)}")

    remote_job = next((j for j in jobs if "4206775" in j.id), None)
    _check("remote job found", remote_job is not None)
    if remote_job:
        _check("title correct", "ServiceNow Expert" in remote_job.title,
               f"got {remote_job.title!r}")
        _check("company correct", remote_job.company == "Four Dragons",
               f"got {remote_job.company!r}")
        _check("salary_min 180000", remote_job.salary_min == 180000,
               f"got {remote_job.salary_min}")
        _check("salary_max 200000", remote_job.salary_max == 200000,
               f"got {remote_job.salary_max}")
        _check("salary_currency USD", remote_job.salary_currency == "USD")
        _check("is_remote True", remote_job.is_remote is True,
               f"location_raw was {remote_job.location!r}")


def test_parser_kernel_engineer():
    print("\n[test] parser: office job with salary")
    adapter = WellfoundAdapter(api_token="dummy", zone="dummy")
    jobs = adapter._parse(FAKE_HTML, max_results=10)

    kernel = next((j for j in jobs if "4206749" in j.id), None)
    _check("kernel job found", kernel is not None)
    if kernel:
        _check("title", "Kernel Engineer" in kernel.title)
        _check("company Vorticity", kernel.company == "Vorticity",
               f"got {kernel.company!r}")
        _check("salary_min 120000", kernel.salary_min == 120000,
               f"got {kernel.salary_min}")
        _check("url correct",
               kernel.url == "https://wellfound.com/jobs/4206749-kernel-engineer-scientific-computing-spu")
        _check("source == wellfound", kernel.source == "wellfound")


def test_parser_no_salary():
    print("\n[test] parser: job without salary stated")
    adapter = WellfoundAdapter(api_token="dummy", zone="dummy")
    jobs = adapter._parse(FAKE_HTML, max_results=10)

    designer = next((j for j in jobs if "9999999" in j.id), None)
    _check("designer job found", designer is not None)
    if designer:
        _check("salary_min is None", designer.salary_min is None,
               f"got {designer.salary_min}")
        _check("salary_currency is None", designer.salary_currency is None)
        _check("company Acme", designer.company == "Acme",
               f"got {designer.company!r}")


def test_parser_max_results_respected():
    print("\n[test] parser: max_results cap")
    adapter = WellfoundAdapter(api_token="dummy", zone="dummy")
    jobs = adapter._parse(FAKE_HTML, max_results=2)
    _check("returns at most 2 jobs", len(jobs) <= 2, f"got {len(jobs)}")


def test_parser_dedup():
    print("\n[test] parser: duplicate job IDs are deduped")
    adapter = WellfoundAdapter(api_token="dummy", zone="dummy")
    doubled = CARD_REMOTE + CARD_REMOTE  # same card twice
    jobs = adapter._parse(doubled, max_results=10)
    _check("only 1 job despite 2 identical cards", len(jobs) == 1,
           f"got {len(jobs)}")


# ---------------------------------------------------------------------------
# Live smoke test (LIVE=1 only — hits Bright Data API)
# ---------------------------------------------------------------------------


async def test_live_search():
    print("\n[test] LIVE: WellfoundAdapter.search() hits real Bright Data API")
    from dotenv import load_dotenv
    load_dotenv()

    token = os.getenv("BRIGHTDATA_API_TOKEN")
    if not token:
        _fail("LIVE config", "BRIGHTDATA_API_TOKEN not set in .env")
        return

    adapter = WellfoundAdapter()
    jobs = await adapter.search("software engineer remote", max_results=10)

    _check("got at least 1 job", len(jobs) >= 1, f"got {len(jobs)}")
    for j in jobs:
        _check(f"  {j.title[:40]!r} has title", bool(j.title))
        _check(f"  {j.title[:40]!r} has company", bool(j.company),
               f"company was empty")
        _check(f"  {j.title[:40]!r} has url",
               j.url.startswith("https://wellfound.com/jobs/"))
        _check(f"  {j.title[:40]!r} source==wellfound", j.source == "wellfound")
        break  # one job is enough for structure checks; saves API credits


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    print("=" * 60)
    print("WellfoundAdapter tests")
    print("=" * 60)

    test_parser_extracts_title_company_salary()
    test_parser_kernel_engineer()
    test_parser_no_salary()
    test_parser_max_results_respected()
    test_parser_dedup()

    if os.environ.get("LIVE") == "1":
        await test_live_search()

    print(f"\n{'=' * 60}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
