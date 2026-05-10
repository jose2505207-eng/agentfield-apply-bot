"""
TailoredResume schema.

Output of tailor_resume. Same SHAPE as ParsedResume so render_pdf can
treat them interchangeably, but with two crucial constraints:

  1. Immutable identity fields (title, company, dates) MUST equal the
     originals. We enforce this in code after the LLM returns.

  2. Audit fields (changes_made, bullets_kept_unchanged) tell us exactly
     what was rephrased so a human can review before sending.

WHY MIRROR THE PARSED RESUME SHAPE INSTEAD OF A "DIFF" SHAPE:
  render_pdf only knows how to render a ParsedResume-like structure.
  If we returned diffs, render_pdf would need to apply them to the
  original. That's coupling we don't want — keep render_pdf dumb and
  keep tailoring as a transform.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class TailoredExperience(BaseModel):
    """Same as Experience, but bullets may be rewritten (others unchanged)."""
    title: str = Field(description="MUST equal the original title verbatim")
    company: str = Field(description="MUST equal the original company verbatim")
    location: Optional[str] = Field(description="MUST equal the original")
    start_date: str = Field(description="MUST equal the original")
    end_date: str = Field(description="MUST equal the original")
    bullets: list[str] = Field(
        description="Same number and order intent as original, but bullets "
                    "with job-relevant content may be rephrased. Bullets "
                    "without overlap to job keywords MUST be returned verbatim."
    )


class TailoredProject(BaseModel):
    """Same as Project but description and bullets may be rewritten."""
    name: str = Field(description="MUST equal the original name verbatim")
    stack: list[str] = Field(description="May be reordered. NO additions, NO removals.")
    description: str = Field(description="May be rephrased to emphasize job-relevant aspects")
    bullets: list[str] = Field(description="Same constraints as TailoredExperience.bullets")


class TailoredSkillCategory(BaseModel):
    name: str = Field(description="MUST equal an original category name")
    items: list[str] = Field(
        description="May be REORDERED to put job-relevant items first. "
                    "NO additions of new skills, NO removals."
    )


class BulletChange(BaseModel):
    """One audit entry: a bullet that was rephrased."""
    section: str = Field(description="Where it lives, e.g., 'Experience: NPI Manufacturing Technician'")
    original: str = Field(description="The bullet exactly as it appeared in the resume")
    rewritten: str = Field(description="The rewritten version sent to the employer")
    rationale: str = Field(description="One sentence: why this rewrite, tied to a job requirement")


class TailoredResume(BaseModel):
    """A resume rewritten to emphasize fit with one specific job posting."""

    # ---- Identity (NEVER changes — copied from ParsedResume verbatim) ----
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    linkedin_url: Optional[str]
    github_url: Optional[str]
    summary: str = Field(description="May be rephrased to emphasize job-relevant aspects")

    # ---- Mutable structure (constrained rewrites only) ----
    experience: list[TailoredExperience]
    projects: list[TailoredProject]
    skills: list[TailoredSkillCategory] = Field(
        description="May be reordered: place categories with most matching skills first."
    )

    # ---- Pass-through (NEVER changes — copied verbatim) ----
    education: list[dict] = Field(description="Education entries copied unchanged from the parsed resume")
    languages: list[str] = Field(description="Copied unchanged")
    awards: list[str] = Field(description="Copied unchanged")

    # ---- Audit trail ----
    changes_made: list[BulletChange] = Field(
        description="Every bullet that was rephrased. Empty list means nothing was changed."
    )
    bullets_kept_unchanged: int = Field(
        description="Count of bullets that were intentionally left alone because "
                    "they had no overlap with job requirements."
    )
