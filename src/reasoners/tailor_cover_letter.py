"""
tailor_cover_letter reasoner — v3 (with marginal-skill filtering).

Change vs v2: the resume is sanitized via filter_marginal_skills() before
being formatted into the prompt. The LLM never sees skills marked as
"(basics)", "(beginner)", "(self-study)", etc. — and so cannot amplify
them into claims of expertise.

This is determinism > prompting: rather than telling the LLM not to use
marginal skills (which it sometimes ignores), we remove them from the input.
"""
from __future__ import annotations

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume
from src.schemas.job import JobPosting, ScoreResult
from src.schemas.cover_letter import CoverLetter
from src.utils.resume_filters import filter_marginal_skills


SYSTEM_PROMPT = """You are an experienced career writer helping a candidate apply to a specific job.
You will be given the candidate's parsed resume, the job posting, and a fit assessment.
Your job: write a tailored cover letter that a hiring manager would actually read past the first line.

# OUTPUT REQUIREMENTS

Structure: exactly 3 body paragraphs.

P1 — HOOK (2-3 sentences):
  Open with a CONCRETE FACT from the candidate's resume that is directly
  relevant to this job. The first 12 words must contain a real proper noun
  (a project, a company, an award, a specific technology shipped to production).
  No generic openers. No statements of intent.

  BAD examples (do not write like this):
    - "I am applying for the X position..."
    - "I am writing to express my interest..."
    - "Your role caught my attention because..."
    - "With a strong background in..."
    - "As an experienced engineer..."

  GOOD examples (write like this):
    - "Last year I shipped agentic-marketing-stack — a production GPT-4o + DALL-E pipeline running real client work — and your AI Engineer posting reads like the next iteration of that work."
    - "The Best Local Impact Award I won at Intuitive Surgical's 2025 AI Fair was for exactly the kind of supervised-learning diagnostic system your job posting describes."

P2 — EVIDENCE (3-5 sentences):
  Tie 2-3 specific resume facts to specific job requirements. Use the verbs
  from the resume bullets exactly. Mention proper nouns: project names,
  technology names, company names. Numbers when present in resume.

P3 — CLOSING (2-3 sentences):
  Not a place to parrot the company's mission or tagline. Instead: one
  sentence connecting candidate's PROVEN strength to a SPECIFIC need the
  job describes; one sentence with a clear next step (availability, call
  to action). No "I am eager to contribute to {company}'s mission".

# HARD RULES

R1. NEVER invent facts. No fabricated years, no metrics absent from resume.
R2. NEVER inflate verbs. "Worked on" is not "led". "Familiar with" is not "expert in".
R3. NEVER cite a metric unless verbatim in the resume.
R4. ALWAYS ground claims. List every cited fact in `key_evidence_used`.
R5. NO empty intensifiers / corporate fluff:
    - "showcasing my ability to..."
    - "demonstrating my capability for..."
    - "highlighting my skills in..."
    - "leveraging my expertise in..."
    - "bringing value through..."
    - "passionate about", "excited to", "thrilled to"
    - "team player", "results-oriented", "go-getter"
    - "proven track record", "synergies", "value-add"
R6. NO restating the job description back at the reader.
R7. NO addressing gaps. Focus on actual strengths.
R8. Match the candidate's actual seniority level inferred from titles and years.

# WHAT GOES IN key_evidence_used

For every concrete claim, add the source:
  - Project name, role + company, award, or specific bullet content.
This is a verifiability checklist.

# TONE

Formal but human. Direct, confident, evidence-first.
"""


def _format_resume(resume: ParsedResume) -> str:
    parts = [
        f"# Candidate: {resume.full_name}",
        f"\n## Summary\n{resume.summary}",
    ]
    parts.append("\n## Experience")
    for exp in resume.experience:
        parts.append(f"\n### {exp.title} @ {exp.company} ({exp.start_date} – {exp.end_date})")
        for b in exp.bullets:
            parts.append(f"- {b}")
    if resume.projects:
        parts.append("\n## Projects")
        for p in resume.projects:
            parts.append(f"\n### {p.name}")
            if p.stack:
                parts.append(f"Stack: {', '.join(p.stack)}")
            parts.append(p.description)
            for b in p.bullets:
                parts.append(f"- {b}")
    if resume.awards:
        parts.append("\n## Awards")
        for a in resume.awards:
            parts.append(f"- {a}")
    parts.append("\n## Skills")
    for cat in resume.skills:
        parts.append(f"- {cat.name}: {', '.join(cat.items)}")
    return "\n".join(parts)


def _format_job(job: JobPosting) -> str:
    parts = [f"# Job: {job.title} @ {job.company}"]
    if job.location:
        parts.append(f"Location: {job.location}{' (remote)' if job.is_remote else ''}")
    parts.append(f"\n## Description\n{job.description}")
    if job.required_skills:
        parts.append(f"\n## Required skills: {', '.join(job.required_skills)}")
    return "\n".join(parts)


def _format_score(score: ScoreResult) -> str:
    parts = [
        f"# Fit Assessment",
        f"Score: {score.score}/100  ({score.verdict})",
        f"Reasoning: {score.reasoning}",
    ]
    if score.matching_skills:
        parts.append(f"\nStrengths to emphasize: {', '.join(score.matching_skills)}")
    if score.strengths:
        parts.append("\nSpecific fit points:")
        for s in score.strengths:
            parts.append(f"  - {s}")
    if score.missing_skills:
        parts.append(f"\nGaps (do NOT address these): {', '.join(score.missing_skills)}")
    return "\n".join(parts)


async def tailor_cover_letter(
    resume: ParsedResume,
    job: JobPosting,
    score: ScoreResult,
) -> CoverLetter:
    """Generate a tailored cover letter, with marginal skills filtered out."""
    # Filter marginal skills BEFORE the LLM sees the resume.
    sanitized = filter_marginal_skills(resume)

    user_prompt = f"""Write a tailored cover letter for this candidate applying to this job.

{_format_resume(sanitized)}

---

{_format_job(job)}

---

{_format_score(score)}

---

Return a structured CoverLetter following the rules above. Open with concrete
evidence, no empty intensifiers, closing must connect a real candidate
strength to a specific company need.
"""
    return await structured_complete(
        schema=CoverLetter,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
