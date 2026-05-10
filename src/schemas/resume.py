"""
Resume schema. Single source of truth for what a parsed resume looks like.
Used by parse_resume (output) and downstream reasoners (input).

Note: All fields are required in OpenAI strict structured outputs mode.
Optional fields use `Optional[T]` (nullable). Empty collections return [].
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Experience(BaseModel):
    title: str = Field(description="Job title or role")
    company: str = Field(description="Company name")
    location: Optional[str] = Field(description="City, State or remote (null if not stated)")
    start_date: str = Field(description="Start date as it appears (e.g. 'Jan 2024', '2024')")
    end_date: str = Field(description="End date or 'Present'")
    bullets: list[str] = Field(description="Achievement / responsibility bullets, verbatim from resume")


class Project(BaseModel):
    name: str
    stack: list[str] = Field(description="Technologies, languages, frameworks")
    description: str = Field(description="What the project does, in 1-3 sentences")
    bullets: list[str] = Field(description="Concrete impact / details bullets")


class Education(BaseModel):
    degree: str
    institution: str
    start_date: Optional[str] = Field(description="Start date or null")
    end_date: Optional[str] = Field(description="End date or null")
    notes: Optional[str] = Field(description="Extra context (honors, GPA, focus areas) or null")


class SkillCategory(BaseModel):
    name: str = Field(description="Category name (e.g. 'Languages', 'AI & Agents', 'Mobile & Web')")
    items: list[str] = Field(description="Skills in this category")


class ParsedResume(BaseModel):
    """Structured representation of a resume PDF."""
    full_name: str
    email: Optional[str] = Field(description="Email or null if not present")
    phone: Optional[str] = Field(description="Phone or null if not present")
    location: Optional[str] = Field(description="City, State or null if not present")
    linkedin_url: Optional[str] = Field(description="LinkedIn URL or null if not present")
    github_url: Optional[str] = Field(description="GitHub URL or null if not present")

    summary: str = Field(description="Professional summary / about section, verbatim")

    experience: list[Experience] = Field(description="Work experience entries, most recent first")
    projects: list[Project] = Field(description="Notable projects (personal or professional)")
    education: list[Education] = Field(description="Education entries")

    skills: list[SkillCategory] = Field(
        description="Skills grouped by the resume's own categories. "
                    "If the resume lists skills as a flat list, use one category named 'General'."
    )
    languages: list[str] = Field(
        description="Spoken/written languages (e.g. ['English', 'Spanish']). Empty list if none."
    )
    awards: list[str] = Field(
        description="Awards, certifications, recognitions worth highlighting. Empty list if none."
    )
