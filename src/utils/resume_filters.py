"""
Resume filters.

Utilities to sanitize a ParsedResume before sending it to an LLM that
generates content for employers (cover letters, tailored resumes).

PRIMARY USE CASE: marginal-skill filtering.
  A skill listed as "Docker (basics)" or "Rust (learning)" signals
  beginner-level familiarity. If the LLM sees it, it tends to amplify
  it into a core claim ("my Docker experience supports..."). The fix
  is to never let the LLM see those skills in the first place.

DESIGN PRINCIPLE:
  Preprocessing > prompting > postprocessing for non-negotiable rules.
  If the data isn't in the input, the model can't put it in the output.
  This is the deterministic alternative to prompt rules the model may
  silently violate.
"""
from __future__ import annotations
import re

from src.schemas.resume import ParsedResume, SkillCategory


# Qualifiers that mark a skill as beginner / not-yet-mastered.
# Case-insensitive substring match against the skill name.
DEFAULT_MARGINAL_MARKERS: tuple[str, ...] = (
    "(basics)",
    "(beginner)",
    "(learning)",
    "(self-study)",
    "(self study)",
    "(intro)",
    "(introduction)",
    "(familiar)",
    "(exposure)",
)


def is_marginal_skill(skill: str, markers: tuple[str, ...] = DEFAULT_MARGINAL_MARKERS) -> bool:
    """Return True if the skill text contains any of the marginal markers."""
    s = skill.lower()
    return any(marker in s for marker in markers)


def filter_marginal_skills(
    resume: ParsedResume,
    markers: tuple[str, ...] = DEFAULT_MARGINAL_MARKERS,
) -> ParsedResume:
    """
    Return a copy of the resume with marginal skills removed.

    A "marginal" skill is one whose text contains any marker (e.g., "(basics)").
    Empty categories (after filtering) are also dropped.

    Args:
        resume: the resume to filter.
        markers: tuple of substring markers (case-insensitive) that
                 identify a marginal skill. Defaults cover the common ones.

    Returns:
        A new ParsedResume (the original is unchanged — Pydantic's model_copy
        gives us deep copy semantics for free).

    Note:
        We do NOT touch bullet text, project descriptions, or the summary.
        Those are written by Jose himself and presumed accurate. We only
        sanitize the SKILLS list because that's where qualifiers live.
    """
    new_categories: list[SkillCategory] = []
    for cat in resume.skills:
        kept_items = [item for item in cat.items if not is_marginal_skill(item, markers)]
        if kept_items:  # drop entirely empty categories
            new_categories.append(SkillCategory(name=cat.name, items=kept_items))

    # Pydantic's model_copy(update=...) returns a new instance with overrides.
    # Other fields (experience, projects, education, etc.) pass through unchanged.
    return resume.model_copy(update={"skills": new_categories})


def diff_skills(before: ParsedResume, after: ParsedResume) -> list[str]:
    """Helper for logging / debugging: what skills did we drop?"""
    before_set = {(c.name, i) for c in before.skills for i in c.items}
    after_set = {(c.name, i) for c in after.skills for i in c.items}
    dropped = before_set - after_set
    return [f"{cat}: {item}" for cat, item in sorted(dropped)]
