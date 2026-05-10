"""
score_match reasoner.

Input:  ParsedResume + JobPosting
Output: ScoreResult (score 0-100, verdict, reasoning, skill breakdown)

This is reasoner #2 in the apply-bot pipeline. Role: gatekeeper.
Decides which jobs are worth the bot's effort to apply to.

WHY AN LLM AND NOT KEYWORD MATCHING:
  Skill names rarely match exactly between CV and JD. "Python" in your
  CV vs "scripting (Python or Ruby)" in the JD — keyword matching fails,
  an LLM understands they overlap. Same for "managed a team" vs
  "leadership experience" — semantic, not lexical, similarity.

WHY temperature=0:
  Determinism. We want score(resume, job) to give the SAME answer on
  reruns during development. The default in our llm/client.py is
  already 0, so we don't override it here.

WHY WE ONLY SEND RELEVANT FIELDS, NOT THE FULL RESUME:
  Token cost (full resume has ~1500 tokens of metadata that don't help
  scoring) and signal-to-noise (phone numbers, addresses, dates of
  education don't change whether you fit a job). The _format_*
  helpers below compress to what matters.
"""
from __future__ import annotations

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume
from src.schemas.job import JobPosting, ScoreResult


# The system prompt encodes the "rules of the game" — the rubric.
# We keep it strict on purpose. An optimistic scorer is useless.
SYSTEM_PROMPT = """You are an experienced technical recruiter evaluating fit between a candidate and a job posting.

Score 0-100 using this rubric:
- 85-100: Strong fit. Most required skills present, experience level aligns. → APPLY
- 70-84:  Good fit. Some gaps but candidate could realistically compete. → APPLY
- 50-69:  Borderline. Notable gaps or partial mismatch. → BORDERLINE (low-effort apply only)
- 0-49:   Poor fit. Major gaps. → SKIP

Be strict. The candidate's time is finite — better to mark borderline/skip than to inflate.

Consider:
- Required skill overlap (heaviest weight)
- Nice-to-have skill overlap (light weight)
- Experience level alignment (junior/mid/senior implied by years and titles)
- Domain fit (industry, type of work)
- Red flags (job needs core skill candidate completely lacks)

Do NOT:
- Inflate scores from optimism or politeness
- Treat adjacent skills as equivalent (Python ≠ Java; React Native ≠ React for web roles)
- Penalize the candidate for missing nice-to-have skills as harshly as required ones

Your reasoning should be concise (2-4 sentences) and tied to specific evidence in the resume and job.
"""


def _format_resume_for_scoring(resume: ParsedResume) -> str:
    """
    Compress resume to fields useful for scoring.

    Drops: contact info, addresses, dates of education, certifications.
    Keeps: summary, skills, job titles + bullets, projects + stacks, languages.
    """
    parts: list[str] = [
        f"# Candidate: {resume.full_name}",
        f"\n## Summary\n{resume.summary}",
        "\n## Skills",
    ]
    for cat in resume.skills:
        parts.append(f"- {cat.name}: {', '.join(cat.items)}")

    parts.append("\n## Experience")
    for exp in resume.experience:
        parts.append(f"\n### {exp.title} @ {exp.company} ({exp.start_date} – {exp.end_date})")
        for bullet in exp.bullets:
            parts.append(f"- {bullet}")

    if resume.projects:
        parts.append("\n## Projects")
        for proj in resume.projects:
            parts.append(f"\n### {proj.name}")
            if proj.stack:
                parts.append(f"Stack: {', '.join(proj.stack)}")
            parts.append(proj.description)

    if resume.languages:
        parts.append(f"\n## Spoken languages: {', '.join(resume.languages)}")

    return "\n".join(parts)


def _format_job_for_scoring(job: JobPosting) -> str:
    """Compress job to scoring-relevant fields."""
    parts: list[str] = [f"# Job: {job.title} @ {job.company}"]

    if job.location:
        remote_str = " (remote)" if job.is_remote else ""
        parts.append(f"Location: {job.location}{remote_str}")
    if job.employment_type:
        parts.append(f"Type: {job.employment_type}")
    if job.salary_min or job.salary_max:
        sal_parts = []
        if job.salary_min: sal_parts.append(f"min {job.salary_min}")
        if job.salary_max: sal_parts.append(f"max {job.salary_max}")
        currency = job.salary_currency or ""
        parts.append(f"Salary: {', '.join(sal_parts)} {currency}".strip())
    if job.years_experience_required:
        parts.append(f"Years experience required: {job.years_experience_required}+")

    parts.append(f"\n## Description\n{job.description}")

    if job.required_skills:
        parts.append(f"\n## Required skills (pre-extracted): {', '.join(job.required_skills)}")
    if job.nice_to_have_skills:
        parts.append(f"## Nice-to-have skills (pre-extracted): {', '.join(job.nice_to_have_skills)}")

    return "\n".join(parts)


async def score_match(resume: ParsedResume, job: JobPosting) -> ScoreResult:
    """
    Score how well a candidate matches a job.

    Args:
        resume: candidate's parsed resume (output of parse_resume)
        job: job posting (output of search_jobs, or hand-crafted for testing)

    Returns:
        ScoreResult with score, verdict, reasoning, and skill breakdown.
    """
    user_prompt = f"""Evaluate this candidate-job match.

{_format_resume_for_scoring(resume)}

---

{_format_job_for_scoring(job)}

---

Return your evaluation as a structured ScoreResult.
"""

    return await structured_complete(
        schema=ScoreResult,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
