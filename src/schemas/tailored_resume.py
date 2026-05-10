"""
TailoredResume schema.

Output of tailor_resume. Same SHAPE as ParsedResume so render_pdf can
treat them interchangeably, but with constraints enforced in the prompt
and again in code post-validation.
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
        description="Same number as original, but bullets with job-relevant "
                    "content may be rephrased. Bullets without overlap to "
                    "job keywords MUST be returned verbatim."
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


class TailoredEducation(BaseModel):
    """Copied verbatim from the parsed resume. Schema mirrors Education."""
    degree: str
    institution: str
    start_date: Optional[str] = Field(description="Start date or null")
    end_date: Optional[str] = Field(description="End date or null")
    notes: Optional[str] = Field(description="Extra context or null")


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
    education: list[TailoredEducation] = Field(description="Copied unchanged from the parsed resume")
    languages: list[str] = Field(description="Copied unchanged")
    awards: list[str] = Field(description="Copied unchanged")

    # ---- Audit trail ----
    changes_made: list[BulletChange] = Field(
        description="Every bullet that was rephrased. Empty list means nothing was changed."
    )
    bullets_kept_unchanged: int = Field(
        description="Count of bullets returned verbatim because no job overlap."
    )
