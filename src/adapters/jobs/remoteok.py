"""
RemoteOK adapter.

Fetches jobs from https://remoteok.com/api (public, no auth required).

API quirks this adapter handles:
  1. Index 0 of the response is a legal/metadata object, not a job.
     We filter by presence of `id` field.
  2. salary_min/salary_max default to 0 when not stated. We convert 0 → None
     so downstream consumers can distinguish "free" from "not stated".
  3. location can be empty string "". We convert "" → None.
  4. description contains HTML (<br/>, <p>, &amp;, etc.). We strip tags
     and unescape entities so reasoners get clean text.

API terms of service: when displaying jobs, we must link back to the original
URL on RemoteOK with a direct link (no redirects). We comply by storing the
original `url` field in JobPosting.url.
"""
from __future__ import annotations
import html
import json
import os
import re
from typing import Any

import httpx

from src.adapters.jobs.base import JobAdapter
from src.schemas.job import JobPosting


REMOTEOK_API_URL = "https://remoteok.com/api"
_BRIGHTDATA_URL = "https://api.brightdata.com/request"

# Match HTML tags. Used for description cleanup.
# Note: this is a simple stripper, not a full HTML parser. Good enough for
# RemoteOK's descriptions which only use basic tags (br, p, ul, li, h1, etc.).
_HTML_TAG = re.compile(r"<[^>]+>")

# RemoteOK descriptions end with a spam-prevention paragraph asking to mention
# a magic word. It pollutes the text we send to the LLM. Strip it.
_REMOTEOK_SPAM_TAIL = re.compile(
    r"Please mention the word.*$",
    flags=re.IGNORECASE | re.DOTALL,
)


def _clean_description(raw: str) -> str:
    """Strip HTML tags, unescape entities, remove RemoteOK's spam tail."""
    if not raw:
        return ""
    # 1. Strip the spam tail BEFORE removing tags (the regex anchors on text).
    cleaned = _REMOTEOK_SPAM_TAIL.sub("", raw)
    # 2. Remove HTML tags.
    cleaned = _HTML_TAG.sub(" ", cleaned)
    # 3. Unescape HTML entities (&amp; → &, &#x27; → ', etc.).
    cleaned = html.unescape(cleaned)
    # 4. Collapse whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _zero_to_none(value: Any) -> int | None:
    """RemoteOK uses 0 to mean "not stated" for salary fields."""
    if value in (0, "0", None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_to_none(value: Any) -> str | None:
    """Convert empty strings to None for cleaner Optional handling."""
    if value is None or value == "":
        return None
    return str(value)


def _matches_query(job_dict: dict, query: str) -> bool:
    """
    Client-side filtering: does this job match the user's free-text query?

    Strategy: normalize the query into individual terms, require ALL of them
    to appear (case-insensitive) somewhere in title/description/tags.

    This is intentionally simple. For better matching we could use embeddings
    or score_match on every job, but at this stage we just want a coarse
    filter to reduce 100 jobs to ~20 relevant ones, and let score_match
    do the smart ranking afterwards.
    """
    if not query:
        return True

    haystack = " ".join([
        str(job_dict.get("position", "")),
        str(job_dict.get("description", "")),
        " ".join(job_dict.get("tags", []) or []),
    ]).lower()

    # All terms must be present (AND, not OR). Quick & dirty but useful.
    terms = [t for t in query.lower().split() if len(t) > 1]
    return all(term in haystack for term in terms)


class RemoteOKAdapter(JobAdapter):
    """Fetches jobs from RemoteOK's public JSON API."""

    source = "remoteok"

    async def _fetch(self) -> list[Any]:
        """Fetch the RemoteOK feed, routing through Bright Data if available.

        RemoteOK blocks datacenter/cloud IPs with a 403. When
        BRIGHTDATA_API_TOKEN is set we route the request through the Web
        Unlocker (residential IPs) to avoid the block.
        """
        token = os.getenv("BRIGHTDATA_API_TOKEN", "")
        zone = os.getenv("BRIGHTDATA_ZONE", "web_unlocker2")
        async with httpx.AsyncClient(timeout=30.0) as client:
            if token:
                r = await client.post(
                    _BRIGHTDATA_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"zone": zone, "url": REMOTEOK_API_URL, "format": "raw"},
                )
            else:
                r = await client.get(
                    REMOTEOK_API_URL,
                    headers={"User-Agent": "agentfield-apply-bot/0.1"},
                )
            r.raise_for_status()
            return json.loads(r.text)

    async def search(self, query: str, max_results: int = 50) -> list[JobPosting]:
        # 1. Fetch the full feed (one HTTP call, returns ~100 jobs).
        data = await self._fetch()

        # 2. Skip index 0 (the legal metadata object — has no `id`).
        raw_jobs = [item for item in data if isinstance(item, dict) and "id" in item]

        # 3. Filter by query (client-side text match).
        matching = [j for j in raw_jobs if _matches_query(j, query)]

        # 4. Cap to max_results.
        matching = matching[:max_results]

        # 5. Map each raw dict into our canonical JobPosting shape.
        return [self._to_job_posting(j) for j in matching]

    def _to_job_posting(self, j: dict) -> JobPosting:
        """Translate one RemoteOK job dict into a JobPosting.

        Note we explicitly set every field, even Optional ones, to None or []
        when RemoteOK doesn't provide them. That way the rest of the system
        never has to wonder "is this missing because RemoteOK doesn't return
        it, or because something went wrong?"
        """
        return JobPosting(
            id=str(j["id"]),
            url=j.get("url") or j.get("apply_url") or "",
            source=self.source,
            title=str(j.get("position", "")),
            company=str(j.get("company", "")),
            description=_clean_description(j.get("description", "")),
            location=_empty_to_none(j.get("location")),
            is_remote=True,  # RemoteOK is remote-only by definition
            salary_min=_zero_to_none(j.get("salary_min")),
            salary_max=_zero_to_none(j.get("salary_max")),
            salary_currency="USD" if j.get("salary_min") else None,  # RemoteOK is USD
            equity_offered=None,  # not exposed
            required_skills=[],  # populated later by extract_requirements reasoner
            nice_to_have_skills=[],
            years_experience_required=None,
            visa_sponsorship=None,
            employment_type=None,  # RemoteOK doesn't expose this consistently
            posted_date=j.get("date"),
            apply_method=None,
        )
