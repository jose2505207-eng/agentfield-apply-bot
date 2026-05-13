"""
WellfoundAdapter — scrapes Wellfound job listings via Bright Data Web Unlocker.

WHY BRIGHT DATA AND NOT DIRECT HTTPX:
  Wellfound blocks headless HTTP clients and CDPs with bot detection
  ("Access is temporarily restricted"). Bright Data's Web Unlocker routes the
  request through residential IPs with real browser fingerprints, bypassing it.

WHAT WE EXTRACT (from the search results page HTML):
  - Job ID + slug → Wellfound URL (used as apply_url)
  - Title, company name, location, salary range, post date
  - Description: skipped at search-time to avoid N+1 fetches per query.
    The score_match and tailor reasoners operate on what we have.

WHY apply_url = wellfound.com/jobs/... AND NOT ATS DIRECT:
  Wellfound dynamically resolves the external ATS URL (Lever/Greenhouse) at
  click time — it's not in the static HTML. For the demo the apply loop
  navigates to the Wellfound job page through the Actionbook browser and
  handles the redirect to the ATS form.

ENV VARS REQUIRED:
  BRIGHTDATA_API_TOKEN  — Bearer token for api.brightdata.com
  BRIGHTDATA_ZONE       — Web Unlocker zone name (default: web_unlocker2)
"""
from __future__ import annotations

import html as _html
import os
import re
from typing import Optional

import httpx

from src.adapters.jobs.base import JobAdapter
from src.schemas.job import JobPosting

_BRIGHTDATA_URL = "https://api.brightdata.com/request"
_WELLFOUND_SEARCH = "https://wellfound.com/jobs?query={query}&remote=true"

# Matches job card link: href="/jobs/4206749-kernel-engineer-..."
_JOB_LINK_RE = re.compile(r'href="(/jobs/(\d+)-([a-z0-9-]+))"')

# After the title link, the card has:
#   <span>COMPANY<!-- --> • </span>
#   <span class="text-gray-700">LOCATION <!-- -->•<!-- --> <!-- -->SALARY • ...</span>
_COMPANY_RE = re.compile(r'<span>([^<]{1,80})(?:<!-- -->)? • </span>')
_META_RE = re.compile(r'<span[^>]*text-gray[^>]*>([^<]*(?:<!-- -->[^<]*)*)</span>')

# Salary range like "$120k – $170k" or "$90k – $150k"
_SALARY_RE = re.compile(r'\$(\d+)k\s*[–-]\s*\$(\d+)k')


def _parse_salary(meta_text: str) -> tuple[Optional[int], Optional[int]]:
    m = _SALARY_RE.search(meta_text)
    if m:
        return int(m.group(1)) * 1000, int(m.group(2)) * 1000
    return None, None


def _clean(text: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", text)).strip()


class WellfoundAdapter(JobAdapter):
    """Fetches remote jobs from Wellfound via Bright Data Web Unlocker."""

    source = "wellfound"

    def __init__(
        self,
        api_token: Optional[str] = None,
        zone: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._token = api_token or os.getenv("BRIGHTDATA_API_TOKEN", "")
        self._zone = zone or os.getenv("BRIGHTDATA_ZONE", "web_unlocker2")
        self._timeout = timeout

    async def _fetch(self, url: str) -> str:
        """Fetch a URL through Bright Data Web Unlocker. Returns HTML text."""
        if not self._token:
            raise RuntimeError(
                "BRIGHTDATA_API_TOKEN not set — cannot use WellfoundAdapter"
            )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                _BRIGHTDATA_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json={"zone": self._zone, "url": url, "format": "raw"},
            )
            r.raise_for_status()
            return r.text

    async def search(self, query: str, max_results: int = 50) -> list[JobPosting]:
        encoded = re.sub(r"\s+", "+", query.strip())
        url = _WELLFOUND_SEARCH.format(query=encoded)
        html_text = await self._fetch(url)
        return self._parse(html_text, max_results)

    def _parse(self, html_text: str, max_results: int) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        seen_ids: set[str] = set()

        # Iterate over all job link occurrences — each is one card.
        for link_m in _JOB_LINK_RE.finditer(html_text):
            if len(jobs) >= max_results:
                break

            path = link_m.group(1)        # /jobs/4206749-kernel-engineer-...
            job_id = link_m.group(2)      # 4206749
            slug = link_m.group(3)        # kernel-engineer-...

            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            # Grab the block of HTML around this link for metadata.
            start = max(0, link_m.start() - 1200)
            end = min(len(html_text), link_m.end() + 600)
            block = html_text[start:end]

            title, company, location_raw, salary_raw = self._extract_card_fields(
                block, path
            )
            if not title:
                continue

            salary_min, salary_max = _parse_salary(salary_raw)

            # is_remote: the search URL already filters for remote=true,
            # but location text may say "Remote" or list a city.
            is_remote = "remote" in location_raw.lower()
            location = _clean(location_raw.split("•")[0]) or None

            jobs.append(
                JobPosting(
                    id=job_id,
                    url=f"https://wellfound.com{path}",
                    source=self.source,
                    title=_clean(title),
                    company=_clean(company),
                    description="",  # not fetched at search time
                    location=location,
                    is_remote=is_remote,
                    salary_min=salary_min,
                    salary_max=salary_max,
                    salary_currency="USD" if salary_min else None,
                    equity_offered=None,
                    required_skills=[],
                    nice_to_have_skills=[],
                    years_experience_required=None,
                    visa_sponsorship=None,
                    employment_type=None,
                    posted_date=None,
                    apply_method="external",
                )
            )

        return jobs

    def _extract_card_fields(
        self, block: str, path: str
    ) -> tuple[str, str, str, str]:
        """Return (title, company, location_raw, salary_raw) from a card HTML block."""
        # Title: text between the job link and its closing </a>
        title_m = re.search(re.escape(path) + r'">([^<]{4,120})</a>', block)
        title = title_m.group(1) if title_m else ""
        if not title:
            return "", "", "", ""

        # Everything after the title link
        after_title = block[title_m.end():]

        # Company: first <span> with pattern "NAME<!-- --> • "
        company_m = _COMPANY_RE.search(after_title)
        company = company_m.group(1).strip() if company_m else ""

        # Location + salary: first gray span after the company span
        meta_start = company_m.end() if company_m else 0
        meta_m = _META_RE.search(after_title[meta_start:])
        if meta_m:
            # Strip React comment nodes <!-- --> and collapse whitespace
            raw = re.sub(r'<!-- -->', ' ', meta_m.group(1))
            raw = re.sub(r'\s+', ' ', raw).strip()
        else:
            raw = ""

        return title, company, raw, raw
