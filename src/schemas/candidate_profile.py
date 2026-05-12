"""
CandidateProfile schema.

The structured personal-data record that apply_to_job feeds to the LLM so it
can answer arbitrary ATS form fields without inventing facts.

WHY SEPARATE FROM ParsedResume:
  - ParsedResume is the OUTPUT of parse_resume — derived from a PDF.
    CandidateProfile is HUMAN-ENTERED — the user fills it once via UI/JSON.
  - The resume changes per job (TailoredResume). The profile NEVER changes
    per job — same work auth, same demographics, same salary expectation,
    same phone number.
  - ATSs ask for fields that resumes don't typically contain: work
    authorization status, EEOC demographic disclosures, salary expectation,
    earliest start date. We need them structured, not buried in prose.

LOAD PATH:
  data/profile.json  --(model_validate_json)-->  CandidateProfile

The frontend (Next.js, later in week) writes the same JSON via a form. The
JSON file is the single source of truth either way.

DESIGN NOTES:
  - All EEOC fields default to 'prefer_not_to_say'. That's a legally valid
    answer on every Greenhouse/Lever/Workday form and avoids the LLM picking
    a demographic for you.
  - work_auth_status is REQUIRED (no default). Getting this wrong on an
    application is consequential; we force the user to declare it.
  - salary_expectation_usd is Optional. When null, the LLM writes
    "Negotiable" or leaves blank, depending on the form.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


WorkAuthStatus = Literal[
    "us_citizen",
    "permanent_resident",
    "h1b",
    "f1_opt",
    "tn_visa",
    "other_authorized",          # legally authorized via some other path
    "needs_sponsorship",         # not currently authorized to work in US
]

GenderAnswer = Literal[
    "male", "female", "non_binary", "prefer_not_to_say",
]

EthnicityAnswer = Literal[
    "hispanic_or_latino",
    "white",
    "black_or_african_american",
    "asian",
    "native_american_or_alaska_native",
    "native_hawaiian_or_pacific_islander",
    "two_or_more_races",
    "prefer_not_to_say",
]

VeteranAnswer = Literal[
    "veteran", "not_a_veteran", "prefer_not_to_say",
]

DisabilityAnswer = Literal[
    "has_disability", "no_disability", "prefer_not_to_say",
]


class CandidateProfile(BaseModel):
    """Personal data the LLM uses to fill any ATS form."""

    # ---- Identity (kept in sync with the PDF resume; this is the form-path copy) ----
    full_name: str
    email: str
    phone: str = Field(
        description="Include country code, e.g. '+1 555 123 4567'. Some ATSs validate format."
    )

    # ---- Location ----
    location_city: str
    location_state: str = Field(description="Two-letter state code if US, full name otherwise")
    location_country: str = Field(description="Two-letter ISO country code, e.g. 'US'")

    # ---- Links (some ATSs ask for these as separate fields) ----
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None

    # ---- Work authorization (required — almost every ATS asks) ----
    work_auth_status: WorkAuthStatus
    requires_visa_sponsorship_now_or_future: bool = Field(
        description="Will you NOW or IN THE FUTURE require visa sponsorship to work in the US? "
                    "This is the exact question Greenhouse/Lever ask."
    )

    # ---- EEOC disclosures (default to prefer_not_to_say) ----
    gender: GenderAnswer = "prefer_not_to_say"
    ethnicity: EthnicityAnswer = "prefer_not_to_say"
    veteran_status: VeteranAnswer = "prefer_not_to_say"
    disability_status: DisabilityAnswer = "prefer_not_to_say"

    # ---- Logistics ----
    salary_expectation_usd: Optional[int] = Field(
        default=None,
        description="Annual salary expectation in USD. Null means LLM writes 'Negotiable' or leaves blank.",
    )
    earliest_start_date: Optional[str] = Field(
        default=None,
        description="ISO date YYYY-MM-DD. Null means 'immediately available' / two weeks notice.",
    )
    willing_to_relocate: bool = False

    # ---- Default answers to recurring open-ended questions ----
    # The LLM may rephrase these per company but should not invent new facts.
    how_did_you_hear: Optional[str] = Field(
        default=None,
        description="Default answer to 'How did you hear about us?'. Null → LLM picks "
                    "from job_source (e.g. 'RemoteOK' for jobs found via RemoteOK).",
    )
    pronouns: Optional[str] = Field(
        default=None,
        description="Some ATSs ask for pronouns explicitly. Null → leave blank.",
    )

    # ---- Safety check ----
    def has_unfilled_placeholders(self) -> list[str]:
        """Return list of fields that still hold obviously-fake placeholder values.

        apply_to_job calls this BEFORE running. If non-empty, refuses to run.
        """
        bad = []
        placeholder_markers = ("FILL_ME", "PLACEHOLDER", "TODO", "@example.com")
        for name in ("full_name", "email", "phone", "location_city"):
            val = getattr(self, name) or ""
            if any(m in val for m in placeholder_markers):
                bad.append(name)
        return bad
