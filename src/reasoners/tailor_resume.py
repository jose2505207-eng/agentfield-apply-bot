"""
tailor_resume reasoner.

Input:  ParsedResume + JobPosting + ScoreResult
Output: TailoredResume (same shape, with bullets rephrased for the job)

Reasoner #5 in the apply-bot pipeline. Last reasoner that touches content
that goes to the employer (after this come render_pdf and apply_to_job
which are mechanical, not creative).

WHY THIS REASONER IS RISKIER THAN tailor_cover_letter:
  Cover letters are obviously generated text — readers expect it to be
  written for them. Resumes are presumed to be biographical fact. A
  rewritten resume that reads identical to the original at a glance can
  hide subtle inflation (e.g., "designed" → "architected", "worked on" →
  "led"). That's why we have:
    1. A strict prompt with explicit verb-mapping rules
    2. Post-validation in code that enforces immutable fields equal originals
    3. Audit trail (changes_made) so a human can spot-check rewrites

WHAT'S MUTABLE vs IMMUTABLE:
  Mutable (LLM may rewrite): summary text, experience bullets, project
    descriptions and bullets, ORDER of skills items.
  Immutable (LLM may NOT change): all titles, companies, locations, dates,
    award names, education entries, languages list, contact info, the
    set of skills (no additions/removals).
"""
from __future__ import annotations

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume
from src.schemas.job import JobPosting, ScoreResult
from src.schemas.tailored_resume import (
    TailoredResume,
    TailoredExperience,
    TailoredProject,
    TailoredSkillCategory,
)


SYSTEM_PROMPT = """You are an expert resume editor. The candidate has applied to
a specific job and you must rewrite their resume bullets to emphasize fit.

You are NOT writing a new resume. You are doing a CONSTRAINED REPHRASE.

# WHAT YOU MAY DO

A. REORDER skills items inside each category to put job-relevant skills first.
B. REORDER bullets within an experience or project so the most job-relevant
   appear first.
C. REPHRASE bullets that have keyword overlap with the job, IF AND ONLY IF
   the rephrase stays factually identical. Examples allowed:
     - "Designed a framework" → "Designed a Python-based framework"
       (added technology that's already in the resume's skills)
     - "Built an n8n workflow" → "Built an automated n8n workflow that converts
       SMS-triggered inputs into completed forms"
       (expanded with detail from elsewhere in the same bullet/resume)
D. REPHRASE the summary in ONE pass to emphasize job-relevant strengths,
   without inventing new facts.

# WHAT YOU MUST NOT DO

E1. NEVER inflate verbs. The verb mapping is one-way:
      "helped with" / "contributed to"  → "contributed to" (max)
      "worked on" / "developed"         → "developed" (max)
      "designed" / "built" / "created"  → keep as-is (do NOT escalate to
                                          "architected", "led", "owned")
      "led" / "owned"                   → keep only if the original used them

E2. NEVER add a skill, technology, or framework that's not already in the
    candidate's resume (somewhere — skills section, bullets, projects, summary).

E3. NEVER add metrics (numbers, percentages, counts) that aren't verbatim
    in the original.

E4. NEVER change titles, companies, locations, dates, award names. Copy
    these EXACTLY as they appear.

E5. NEVER expand a bullet to claim broader scope than original.
    "Built an SMS-to-form workflow" cannot become "Architected the company's
    SMS automation infrastructure".

E6. NEVER rephrase a bullet that has zero keyword overlap with the job.
    Return those verbatim. (This keeps the rewrite minimal and reviewable.)

# FOR EACH BULLET YOU REWRITE

You must add a BulletChange entry to `changes_made` with:
  - section: where the bullet lives
  - original: the bullet text exactly as in the resume
  - rewritten: your version
  - rationale: ONE sentence tying the change to a specific job requirement

If `changes_made` is empty, you didn't rewrite anything. That's fine for
borderline jobs but unusual for high-fit ones.

# COUNT OF UNCHANGED BULLETS

Track in `bullets_kept_unchanged`: count of bullets you returned verbatim
because they had no job overlap. This + len(changes_made) should equal
the total number of bullets across experience and projects.

# IMMUTABLE PASS-THROUGH

For these, copy the values from the input resume exactly:
  - full_name, email, phone, location, linkedin_url, github_url
  - all titles, companies, locations, dates in experience
  - all project names
  - skills set (only ORDER may change; not the items themselves)
  - education (copy each entry as a dict with the same keys)
  - languages
  - awards

The schema requires you to fill these — fill them with the originals.
"""


def _format_resume(resume: ParsedResume) -> str:
    """Full resume dump — for tailoring we want all evidence available."""
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
    if job.nice_to_have_skills:
        parts.append(f"## Nice-to-have: {', '.join(job.nice_to_have_skills)}")
    return "\n".join(parts)


def _format_score_signals(score: ScoreResult) -> str:
    """Tell the LLM where to focus."""
    parts = ["# Tailoring Signals"]
    parts.append(f"\nMatching skills (emphasize these): {', '.join(score.matching_skills)}")
    parts.append(f"\nMissing skills (DO NOT pretend candidate has these): {', '.join(score.missing_skills)}")
    if score.strengths:
        parts.append("\nStrengths to surface in rewrites:")
        for s in score.strengths:
            parts.append(f"  - {s}")
    return "\n".join(parts)


def _enforce_immutable_fields(
    tailored: TailoredResume, original: ParsedResume
) -> tuple[TailoredResume, list[str]]:
    """
    Post-validation: snap immutable fields back to originals if the LLM
    drifted, and report what was corrected.

    Why: defense in depth. The prompt forbids changes to titles/dates,
    but a 5-cent insurance policy never hurts in production code.
    """
    violations: list[str] = []

    # Identity fields
    for field in ("full_name", "email", "phone", "location",
                  "linkedin_url", "github_url"):
        orig_val = getattr(original, field)
        new_val = getattr(tailored, field)
        if orig_val != new_val:
            violations.append(f"{field}: {new_val!r} → restored to {orig_val!r}")
            setattr(tailored, field, orig_val)

    # Experience: titles/companies/dates immutable; bullets count must match
    for i, (orig_exp, new_exp) in enumerate(zip(original.experience, tailored.experience)):
        for field in ("title", "company", "location", "start_date", "end_date"):
            if getattr(orig_exp, field) != getattr(new_exp, field):
                violations.append(
                    f"experience[{i}].{field}: changed; restored"
                )
                setattr(new_exp, field, getattr(orig_exp, field))
        if len(orig_exp.bullets) != len(new_exp.bullets):
            violations.append(
                f"experience[{i}].bullets: count mismatch "
                f"({len(orig_exp.bullets)} → {len(new_exp.bullets)})"
            )

    # Projects: name immutable, stack must be subset of original (no additions)
    for i, (orig_p, new_p) in enumerate(zip(original.projects, tailored.projects)):
        if orig_p.name != new_p.name:
            violations.append(f"project[{i}].name: changed; restored")
            new_p.name = orig_p.name
        added = set(s.lower() for s in new_p.stack) - set(s.lower() for s in orig_p.stack)
        if added:
            violations.append(f"project[{i}].stack: added new items {added}")

    return tailored, violations


async def tailor_resume(
    resume: ParsedResume,
    job: JobPosting,
    score: ScoreResult,
) -> tuple[TailoredResume, list[str]]:
    """
    Tailor a resume to a specific job posting.

    Returns:
        (tailored_resume, validation_warnings)
        validation_warnings is a list of immutable-field violations the
        LLM produced and we corrected. Empty list means the LLM behaved.
        If non-empty, log/display these — they signal prompt drift.
    """
    user_prompt = f"""Rewrite the candidate's resume to emphasize fit with the target job.

Follow the rules in the system message strictly. Use [bN] indices to refer to
specific bullets in your changes_made entries (e.g., "Experience: NPI role, b2").

{_format_resume(resume)}

---

{_format_job(job)}

---

{_format_score_signals(score)}

---

Return a structured TailoredResume. Remember:
  - Only rewrite bullets that overlap with job keywords; return others verbatim
  - Never inflate verbs, never add skills/metrics that aren't already present
  - Copy all titles, companies, dates, award names, and education entries verbatim
  - Every rewrite goes in changes_made with a rationale
"""
    tailored = await structured_complete(
        schema=TailoredResume,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
    tailored, violations = _enforce_immutable_fields(tailored, resume)
    return tailored, violations
