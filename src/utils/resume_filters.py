"""
Resume filters.

Utilities to sanitize a ParsedResume and related objects before sending
them to an LLM that generates content for employers.

PRIMARY USE CASE: marginal-skill filtering.
  A skill listed as "Docker (basics)" or "Rust (learning)" signals
  beginner-level familiarity. If the LLM sees it (anywhere — in the resume,
  in a ScoreResult, in any auxiliary context), it tends to amplify it
  into a core claim. The fix is to never let it reach the prompt.

DESIGN PRINCIPLE:
  Preprocessing > prompting > postprocessing for non-negotiable rules.
  If the data isn't in the input, the model can't put it in the output.

DEFENSE IN DEPTH:
  filter_marginal_skills sanitizes the resume.
  filter_marginal_from_score sanitizes the score's skill lists.
  Both must be applied before the LLM call — neither alone is enough,
  because the LLM can mention a skill it sees in EITHER input.
"""
from __future__ import annotations
import re

from src.schemas.resume import ParsedResume, SkillCategory
from src.schemas.job import ScoreResult


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


def _marginal_bare_names(
    resume: ParsedResume, markers: tuple[str, ...] = DEFAULT_MARGINAL_MARKERS
) -> set[str]:
    """
    Extract the bare names of marginal skills (without the qualifier).

    E.g., "Docker (basics)" → "docker"
          "Rust (beginner)" → "rust"

    Used to detect when ScoreResult fields mention these skills under
    their plain name (which they will — score_match doesn't carry the
    qualifier through).
    """
    names: set[str] = set()
    for cat in resume.skills:
        for item in cat.items:
            if is_marginal_skill(item, markers):
                bare = item
                for marker in markers:
                    bare = re.sub(re.escape(marker), "", bare, flags=re.IGNORECASE)
                bare = bare.strip().strip("()").strip().lower()
                if bare:
                    names.add(bare)
    return names


def filter_marginal_skills(
    resume: ParsedResume,
    markers: tuple[str, ...] = DEFAULT_MARGINAL_MARKERS,
) -> ParsedResume:
    """Return a copy of the resume with marginal skills removed."""
    new_categories: list[SkillCategory] = []
    for cat in resume.skills:
        kept_items = [item for item in cat.items if not is_marginal_skill(item, markers)]
        if kept_items:
            new_categories.append(SkillCategory(name=cat.name, items=kept_items))
    return resume.model_copy(update={"skills": new_categories})


def filter_marginal_from_score(
    score: ScoreResult,
    resume: ParsedResume,
    markers: tuple[str, ...] = DEFAULT_MARGINAL_MARKERS,
) -> ScoreResult:
    """
    Return a copy of the ScoreResult with mentions of marginal skills
    removed from matching_skills, missing_skills, strengths, and concerns.

    Why: score_match runs BEFORE filtering and sees the original resume
    (which is correct for accurate scoring — we want the true fit number).
    But when we pass score to a content-generation reasoner, mentions
    of marginal skills in its lists become a leak vector to the LLM.

    The resume is used to identify WHICH skills are marginal.
    """
    bare_names = _marginal_bare_names(resume, markers)
    if not bare_names:
        return score

    def _scrub_list(lst: list[str]) -> list[str]:
        """Remove items that mention a marginal skill (case-insensitive)."""
        return [
            item for item in lst
            if not any(name in item.lower() for name in bare_names)
        ]

    def _scrub_text(text: str) -> str:
        """Remove sentences from text that mention a marginal skill."""
        # Naive sentence split. Good enough for short reasoning blurbs.
        sentences = re.split(r"(?<=[.!?])\s+", text)
        kept = [
            s for s in sentences
            if not any(name in s.lower() for name in bare_names)
        ]
        return " ".join(kept).strip()

    return score.model_copy(update={
        "matching_skills": _scrub_list(score.matching_skills),
        "missing_skills": _scrub_list(score.missing_skills),
        "strengths": _scrub_list(score.strengths),
        "concerns": _scrub_list(score.concerns),
        "reasoning": _scrub_text(score.reasoning),
    })


def diff_skills(before: ParsedResume, after: ParsedResume) -> list[str]:
    """Helper for logging: what skills did we drop?"""
    before_set = {(c.name, i) for c in before.skills for i in c.items}
    after_set = {(c.name, i) for c in after.skills for i in c.items}
    dropped = before_set - after_set
    return [f"{cat}: {item}" for cat, item in sorted(dropped)]
