"""
search_jobs — orchestrator for fetching jobs across multiple sources.

This is NOT a reasoner in the LLM sense (it makes zero LLM calls). It's a
plain function that delegates to one or more adapters and merges results.

Why it lives in src/reasoners/ anyway: from the pipeline's perspective, it's
a step that takes input (a query) and produces output (jobs) just like every
other reasoner. Naming consistency over taxonomical purity.

Usage:
    jobs = await search_jobs("AI engineer remote python", sources=["remoteok"])
"""
from __future__ import annotations
import asyncio

from src.adapters.jobs.base import JobAdapter
from src.adapters.jobs.remoteok import RemoteOKAdapter
from src.schemas.job import JobPosting


# Registry: source name → adapter instance.
# To add a new source, write a new adapter, import it, and add a line here.
# That's it. No other file needs to change.
ADAPTERS: dict[str, JobAdapter] = {
    "remoteok": RemoteOKAdapter(),
    # "wellfound": WellfoundAdapter(),   # added Day 6
    # "greenhouse": GreenhouseAdapter(),
}


async def search_jobs(
    query: str,
    sources: list[str] | None = None,
    max_per_source: int = 50,
) -> list[JobPosting]:
    """
    Fetch jobs matching `query` from one or more sources.

    Args:
        query: Free-text search.
        sources: List of source names to query. None = all registered sources.
        max_per_source: Cap on how many jobs each adapter returns.

    Returns:
        Deduplicated, merged list of JobPosting from all sources.
        If one adapter fails, others still return; the failure is printed
        but not raised. (Resilience over strictness — we'd rather have
        partial results than no results at all.)
    """
    if sources is None:
        sources = list(ADAPTERS.keys())

    # Run all adapters in parallel — they're I/O bound so this is a real win
    # when we have multiple sources. With one source it's a no-op.
    tasks = [_safe_search(name, query, max_per_source) for name in sources]
    results = await asyncio.gather(*tasks)

    # Flatten and deduplicate by (source, id).
    seen: set[tuple[str, str]] = set()
    merged: list[JobPosting] = []
    for jobs in results:
        for job in jobs:
            key = (job.source, job.id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(job)

    return merged


async def _safe_search(source_name: str, query: str, max_results: int) -> list[JobPosting]:
    """Wrap an adapter's search() so one failure doesn't break the others."""
    adapter = ADAPTERS.get(source_name)
    if adapter is None:
        print(f"  [search_jobs] unknown source: {source_name!r} (skipped)")
        return []
    try:
        return await adapter.search(query, max_results=max_results)
    except Exception as e:
        print(f"  [search_jobs] adapter {source_name!r} failed: {type(e).__name__}: {e}")
        return []
