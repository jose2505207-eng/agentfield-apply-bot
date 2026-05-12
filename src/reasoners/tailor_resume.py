"""
tailor_resume reasoner — v3 (defense-in-depth marginal filtering).

Change vs v2: applies filter_marginal_from_score in addition to
filter_marginal_skills on the resume. Same rationale as the cover
letter reasoner — Docker can leak via the ScoreResult's matching_skills.
"""
from __future__ import annotations

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume, SkillCategory
from src.schemas.job import JobPosting, ScoreResult
from src.schemas.tailored_resume import (
    TailoredResume,
    TailoredSkillCategory,
)
from src.utils.resume_filters import (
    filter_marginal_skills,
    filter_marginal_from_score,
    is_marginal_skill,
)


SYSTEM_PROMPT = """You are an expert resume editor. The candidate has applied to
a specific job and you must rewrite their resume bullets to emphasize fit.

You are NOT writing a new resume. You are doing a CONSTRAINED REPHRASE.

# WHAT YOU MAY DO

A. REORDER skills items inside each category to put job-relevant skills first.
B. REORDER bullets within an experience or project so the most job-relevant
   appear first.
C. REPHRASE bullets that have keyword overlap with the job, IF the rephrase
   stays factually identical.
D. REPHRASE the summary in ONE pass to emphasize job-relevant strengths.

# WHAT YOU MUST NOT DO

E1. NEVER inflate verbs:
      "helped with" / "contributed to"  → "contributed to" (max)
      "worked on" / "developed"         → "developed" (max)
      "designed" / "built" / "created"  → keep as-is
      "led" / "owned"                   → keep only if the original used them

E2. NEVER add a skill, technology, or framework that's not in the resume.

E3. NEVER modify a skill's text. Return each skill exactly as it appears.

E4. NEVER add metrics not verbatim in the original.

E5. NEVER change titles, companies, locations, dates, award names.

E6. NEVER expand a bullet to claim broader scope than original.

E7. NEVER rephrase a bullet with zero keyword overlap with the job — return verbatim.

# AUDIT TRAIL

For each rewrite, add a BulletChange entry with section, original, rewritten,
and rationale tied to a specific job requirement.

# IMMUTABLE PASS-THROUGH

Copy from the input resume verbatim: contact info, all titles/companies/dates,
project names, the skills set (only ORDER may change), education entries,
languages, awards.
"""


def _format_resume(resume: ParsedResume) -> str:
    parts = [
        f"# Candidate: {resume.full_name}",
        f"\n## Summary\n{resume.summary}",
        "\n## Experience",
    ]
    for exp in resume.experience:
        parts.append(f"\n### {exp.title} @ {exp.company} ({exp.start_date} – {exp.end_date})")
        if exp.location:
            parts.append(f"Location: {exp.location}")
        for i, b in enumerate(exp.bullets):
            parts.append(f"  [b{i}] {b}")
    if resume.projects:
        parts.append("\n## Projects")
        for proj in resume.projects:
            parts.append(f"\n### {proj.name}")
            if proj.stack:
                parts.append(f"Stack: {', '.join(proj.stack)}")
            parts.append(f"Description: {proj.description}")
            for i, b in enumerate(proj.bullets):
                parts.append(f"  [b{i}] {b}")
    parts.append("\n## Skills")
    for cat in resume.skills:
        parts.append(f"- {cat.name}: {', '.join(cat.items)}")
    if resume.education:
        parts.append("\n## Education")
        for edu in resume.education:
            parts.append(f"- {edu.degree} @ {edu.institution}")
    if resume.languages:
        parts.append(f"\n## Languages: {', '.join(resume.languages)}")
    if resume.awards:
        parts.append("\n## Awards")
        for a in resume.awards:
            parts.append(f"- {a}")
    return "\n".join(parts)


def _format_job(job: JobPosting) -> str:
    parts = [f"# Target Job: {job.title} @ {job.company}"]
    parts.append(f"\n## Description\n{job.description}")
    if job.required_skills:
        parts.append(f"\n## Required skills: {', '.join(job.required_skills)}")
    return "\n".join(parts)


def _format_score_signals(score: ScoreResult) -> str:
    parts = ["# Tailoring Signals"]
    parts.append(f"\nMatching skills: {', '.join(score.matching_skills)}")
    parts.append(f"\nMissing skills (do NOT claim): {', '.join(score.missing_skills)}")
    if score.strengths:
        parts.append("\nStrengths to surface:")
        for s in score.strengths:
            parts.append(f"  - {s}")
    return "\n".join(parts)


def _merge_marginal_skills_back(
    tailored: TailoredResume, original: ParsedResume
) -> None:
    """The LLM never saw marginal skills. Add them back at the END of each category."""
    marginal_by_cat: dict[str, list[str]] = {}
    for cat in original.skills:
        marginals = [item for item in cat.items if is_marginal_skill(item)]
        if marginals:
            marginal_by_cat[cat.name] = marginals

    if not marginal_by_cat:
        return

    seen_categories = set()
    for cat in tailored.skills:
        seen_categories.add(cat.name)
        if cat.name in marginal_by_cat:
            for item in marginal_by_cat[cat.name]:
                if item not in cat.items:
                    cat.items.append(item)

    for cat_name, items in marginal_by_cat.items():
        if cat_name not in seen_categories:
            tailored.skills.append(
                TailoredSkillCategory(name=cat_name, items=list(items))
            )


def _enforce_immutable_fields(
    tailored: TailoredResume, original: ParsedResume
) -> tuple[TailoredResume, list[str]]:
    """Snap immutable fields back to originals if the LLM drifted."""
    violations: list[str] = []

    for field in ("full_name", "email", "phone", "location",
                  "linkedin_url", "github_url"):
        if getattr(original, field) != getattr(tailored, field):
            violations.append(f"{field}: restored from LLM-drifted value")
            setattr(tailored, field, getattr(original, field))

    for i, (orig, new) in enumerate(zip(original.experience, tailored.experience)):
        for f in ("title", "company", "location", "start_date", "end_date"):
            if getattr(orig, f) != getattr(new, f):
                violations.append(f"experience[{i}].{f}: restored")
                setattr(new, f, getattr(orig, f))
        if len(orig.bullets) != len(new.bullets):
            violations.append(
                f"experience[{i}].bullets: count mismatch "
                f"({len(orig.bullets)} → {len(new.bullets)})"
            )

    for i, (orig, new) in enumerate(zip(original.projects, tailored.projects)):
        if orig.name != new.name:
            violations.append(f"project[{i}].name: restored")
            new.name = orig.name
        added = set(s.lower() for s in new.stack) - set(s.lower() for s in orig.stack)
        if added:
            violations.append(f"project[{i}].stack: added items {added}")

    return tailored, violations


async def tailor_resume(
    resume: ParsedResume,
    job: JobPosting,
    score: ScoreResult,
) -> tuple[TailoredResume, list[str]]:
    """Tailor a resume with double-filtered inputs and post-validation."""
    sanitized_resume = filter_marginal_skills(resume)
    sanitized_score = filter_marginal_from_score(score, resume)

    user_prompt = f"""Rewrite the candidate's resume to emphasize fit with the target job.

Follow the rules strictly. Use [bN] indices to refer to specific bullets in
your changes_made entries.

{_format_resume(sanitized_resume)}

---

{_format_job(job)}

---

{_format_score_signals(sanitized_score)}

---

Return a structured TailoredResume. Only rewrite bullets with job-keyword
overlap; return others verbatim. Never inflate verbs, never add skills.
"""
    tailored = await structured_complete(
        schema=TailoredResume,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
    _merge_marginal_skills_back(tailored, resume)
    tailored, violations = _enforce_immutable_fields(tailored, resume)
    return tailored, violations
