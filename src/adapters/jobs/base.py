"""
JobAdapter — contract that all job-source adapters must satisfy.

Every place we want to fetch jobs from (RemoteOK, Wellfound, Greenhouse, etc.)
gets its own subclass that implements this interface.

The orchestrator (search_jobs) only knows about JobAdapter. It doesn't care
whether a particular adapter talks to a JSON API or scrapes a browser — it
only knows that .search(query) returns a list[JobPosting].
"""
from __future__ import annotations
from abc import ABC, abstractmethod

from src.schemas.job import JobPosting


class JobAdapter(ABC):
    """Abstract base class. Every job-source adapter inherits from this."""

    # Each subclass MUST set this. Used for tagging the JobPosting.source field
    # and for the ADAPTERS registry in search_jobs.py.
    source: str

    @abstractmethod
    async def search(self, query: str, max_results: int = 50) -> list[JobPosting]:
        """
        Search for jobs matching `query` and return up to `max_results`.

        Args:
            query: Free-text search (e.g. "AI engineer remote python").
            max_results: Hard ceiling on how many jobs to return.

        Returns:
            List of JobPosting objects. Each must have its `source` field
            set to self.source (so the orchestrator knows where it came from).

        Implementations should:
            - Handle their own auth / API keys / browser sessions internally
            - Translate the source's native shape into JobPosting (Optional
              fields stay null when the source doesn't expose that data)
            - Raise on hard failures (network down, auth failed); the
              orchestrator will catch and skip a failed adapter
        """
        ...
