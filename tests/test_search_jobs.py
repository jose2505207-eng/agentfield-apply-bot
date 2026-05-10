"""
Smoke test for search_jobs.

Hits the REAL RemoteOK API. No LLM calls, so this test is free.

Run with:
  python -m tests.test_search_jobs

What success looks like:
  - At least 1 job returned (RemoteOK posts hundreds daily — if we get 0,
    either the API is down or the query is too narrow).
  - Every job has a non-empty title, company, description, and url.
  - Every job has source="remoteok".
  - Descriptions are cleaned (no <br/> or "Please mention the word" tail).
  - is_remote is always True.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reasoners.search_jobs import search_jobs


async def main():
    # Try a moderately specific query. Too broad ("python") returns too many;
    # too narrow ("rust solana ai") might return 0 some days.
    query = "engineer python"
    print(f"Searching RemoteOK for: {query!r}\n")

    jobs = await search_jobs(query, sources=["remoteok"], max_per_source=20)

    print(f"Got {len(jobs)} jobs.\n")
    assert len(jobs) > 0, (
        "No jobs returned. Either RemoteOK is down, the query is too narrow, "
        "or the adapter is broken."
    )

    # Show the first 5 in compact form so you can eyeball the parsing quality.
    for i, job in enumerate(jobs[:5], 1):
        print(f"--- Job {i} ---")
        print(f"  id:          {job.id}")
        print(f"  source:      {job.source}")
        print(f"  title:       {job.title}")
        print(f"  company:     {job.company}")
        print(f"  location:    {job.location}")
        print(f"  is_remote:   {job.is_remote}")
        salary_str = "not stated"
        if job.salary_min or job.salary_max:
            salary_str = f"{job.salary_min} - {job.salary_max} {job.salary_currency}"
        print(f"  salary:      {salary_str}")
        print(f"  posted:      {job.posted_date}")
        print(f"  url:         {job.url}")
        # First 200 chars of description so we can verify cleaning worked.
        desc_preview = job.description[:200].replace("\n", " ")
        print(f"  description: {desc_preview}{'...' if len(job.description) > 200 else ''}")
        print()

    # Hard assertions — these catch regressions.
    for job in jobs:
        assert job.title, f"empty title on job {job.id}"
        assert job.company, f"empty company on job {job.id}"
        assert job.description, f"empty description on job {job.id}"
        assert job.url, f"empty url on job {job.id}"
        assert job.source == "remoteok", f"wrong source on job {job.id}: {job.source}"
        assert job.is_remote is True, f"is_remote not True on job {job.id}"
        # Description should be cleaned: no HTML tags, no spam tail.
        assert "<br" not in job.description.lower(), f"HTML not cleaned on job {job.id}"
        assert "<p>" not in job.description.lower(), f"HTML not cleaned on job {job.id}"
        assert "please mention the word" not in job.description.lower(), (
            f"Spam tail not stripped on job {job.id}"
        )

    print(f"✓ All {len(jobs)} jobs passed structural assertions.")
    print(f"✓ Eyeball check: descriptions should look clean (no HTML, no spam tail).")


if __name__ == "__main__":
    asyncio.run(main())
