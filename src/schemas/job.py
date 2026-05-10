"""
Job-related schemas.

JobPosting: a job that we found via search_jobs (or hand-crafted for testing).
            Consumed by score_match, tailor_cover_letter, tailor_resume,
            and apply_to_job.

ScoreResult: the output of score_match. Tells us which jobs deserve an
             application and why.

WHY "COMPLETE" RATHER THAN "MINIMAL":
We chose to define every plausible field upfront so that all downstream
reasoners share one canonical shape. The trade-off: many fields will be
None/empty for jobs from sources that don't expose them (e.g., RemoteOK's
API doesn't give salary ranges; Wellfound's web pages don't always show
visa sponsorship). That's fine — Optional fields handle missing data
cleanly, and we never have to refactor the schema later.

WHICH FIELDS COME FROM WHERE (preview):
  - search_jobs (fetches from API/scraping):
      id, url, source, title, company, description, location, is_remote,
      salary_min/max, employment_type, posted_date
  - extract_requirements (future reasoner using LLM on description text):
      required_skills, nice_to_have_skills, years_experience_required,
      visa_sponsorship, equity_offered
  - apply_to_job (analyzes the application page):
      apply_method
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


class JobPosting(BaseModel):
    """A canonical job posting from any source (RemoteOK, Wellfound, etc.)."""

    # ---- Identity (always present, used for dedup and linking) ----
    id: str = Field(description="Source-specific unique ID, used for deduplication across runs")
    url: str = Field(description="Canonical URL where the job can be viewed and applied to")
    source: str = Field(description="Where the job came from: 'remoteok', 'wellfound', 'greenhouse', etc.")

    # ---- Basics (always present from any source) ----
    title: str
    company: str
    description: str = Field(description="Full job description text")

    # ---- Location ----
    location: Optional[str] = Field(description="Location string ('San Francisco, CA', 'Remote', etc.) or null")
    is_remote: bool = Field(description="True if remote-eligible (derived from location/tags by search_jobs)")

    # ---- Compensation (often missing) ----
    salary_min: Optional[int] = Field(description="Minimum annual salary in salary_currency, null if not stated")
    salary_max: Optional[int] = Field(description="Maximum annual salary, null if not stated")
    salary_currency: Optional[str] = Field(description="ISO currency code (e.g., 'USD'), null if not stated")
    equity_offered: Optional[bool] = Field(description="True if equity mentioned, null if unknown")

    # ---- Requirements (filled by extract_requirements reasoner later) ----
    required_skills: list[str] = Field(description="Skills the posting marks as required. Empty if not yet extracted.")
    nice_to_have_skills: list[str] = Field(description="Skills marked as preferred/nice-to-have. Empty if not yet extracted.")
    years_experience_required: Optional[int] = Field(description="Minimum years expected, null if unspecified")
    visa_sponsorship: Optional[bool] = Field(description="True if employer sponsors visas, null if unknown")

    # ---- Application meta ----
    employment_type: Optional[str] = Field(description="'full_time', 'contract', 'internship', etc., or null")
    posted_date: Optional[str] = Field(description="ISO date when posted, or null")
    apply_method: Optional[str] = Field(description="'easy_apply', 'external', 'email', etc., or null")


class ScoreResult(BaseModel):
    """Result of comparing a candidate's resume to a job posting.

    The shape was chosen so that downstream reasoners (especially tailor_resume
    and tailor_cover_letter) get exactly what they need:
      - matching_skills tells tailor_resume which bullets to emphasize
      - missing_skills tells tailor_resume what NOT to claim falsely
      - strengths/concerns feed the cover letter narrative
      - reasoning is shown to the user/judges for transparency
    """

    score: int = Field(description="0-100 fit score. See rubric in score_match system prompt.")
    verdict: Literal["apply", "borderline", "skip"] = Field(
        description="Categorical decision: apply (>=70), borderline (50-69), skip (<50)"
    )
    reasoning: str = Field(description="2-4 sentence explanation tied to evidence in resume and job posting")

    matching_skills: list[str] = Field(description="Candidate skills that align with job requirements")
    missing_skills: list[str] = Field(description="Required skills the candidate doesn't appear to have")

    strengths: list[str] = Field(description="Specific points where the candidate is a strong fit")
    concerns: list[str] = Field(description="Potential red flags or weaknesses for this application")
