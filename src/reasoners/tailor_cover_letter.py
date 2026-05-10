"""
tailor_cover_letter reasoner — v2 (refined prompt).

Changes from v1 (based on real output review):
  1. Added "marginal skill" rule: skills marked "(basics)" or only listed
     in skills section without bullet evidence cannot be amplified into
     core narrative claims. (Fixes Docker-style hallucination.)
  2. Hook rules now have explicit good/bad examples instead of just bans.
  3. Banned phrase list expanded with the "showcasing my ability" family
     of empty intensifiers.
  4. Added explicit P3 (closing) rule: must tie candidate evidence to
     a concrete company need, not parrot their tagline.
"""
from __future__ import annotations

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume
from src.schemas.job import JobPosting, ScoreResult
from src.schemas.cover_letter import CoverLetter


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
  This is NOT a place to parrot the company's mission or tagline. Instead:
  one sentence connecting candidate's PROVEN strength to a SPECIFIC need
  the job describes; one sentence with a clear next step (availability,
  call to action). No "I am eager to contribute to {company}'s mission".

# HARD RULES (violating these = rejected output)

R1. NEVER invent facts. No fabricated years, no metrics absent from resume.

R2. NEVER amplify marginal skills. If a skill is listed with "(basics)",
    "(beginner)", "(self-study)", or appears ONLY in the skills section
    without supporting bullet/project evidence, you may NOT make it a
    central claim. You MAY mention it briefly as familiarity, never as
    expertise. Example: a resume saying "Docker (basics)" cannot become
    "my Docker experience supports my deployment capabilities".

R3. NEVER inflate verbs. "Worked on" is not "led". "Contributed to" is
    not "owned". "Familiar with" is not "expert in".

R4. NEVER cite a metric (number, %, count) unless verbatim in the resume.

R5. ALWAYS ground claims in evidence. List every cited fact in
    `key_evidence_used`. If you can't list it, don't write it.

R6. NO empty intensifiers / corporate fluff:
    - "showcasing my ability to..."
    - "demonstrating my capability for..."
    - "highlighting my skills in..."
    - "leveraging my expertise in..."
    - "bringing value through..."
    - "passionate about", "excited to", "thrilled to"
    - "team player", "results-oriented", "go-getter", "self-starter"
    - "proven track record", "synergies", "value-add"

R7. NO restating the job description. The reader wrote it; they don't
    need it back.

R8. NO addressing gaps. If the job requires a skill the candidate lacks,
    do not mention the gap. Focus on actual strengths.

R9. Match the candidate's actual seniority. Read the years and titles in
    the resume. Don't write a senior letter for a junior.

# WHAT GOES IN key_evidence_used

For every concrete claim, add the source:
  - Project name (e.g., "agentic-marketing-stack project")
  - Job + company (e.g., "NPI role at Intuitive Surgical")
  - Award (e.g., "Best Local Impact Award 2025")
  - Specific bullet content (e.g., "scikit-learn diagnostic framework")
This is a verifiability checklist. If a claim has no entry here, it
shouldn't be in the letter.

# TONE

Formal but human. Direct, confident, evidence-first. The candidate is a
builder, not a job applicant — they should sound like someone who has
actually shipped things.
"""


# ---------------------------------------------------------------------------
# The formatting helpers below are unchanged from v1. They live here so the
# reasoner is self-contained.
# ---------------------------------------------------------------------------

def _format_resume(resume: ParsedResume) -> str:
    """Compress resume for the prompt — keep what matters for evidence."""
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
    """Pass the score's narrative so the LLM knows what to emphasize."""
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
        parts.append(f"\nGaps (do NOT address these in the letter): {', '.join(score.missing_skills)}")
    return "\n".join(parts)


async def tailor_cover_letter(
    resume: ParsedResume,
    job: JobPosting,
    score: ScoreResult,
) -> CoverLetter:
    """
    Generate a tailored cover letter for a specific job application.

    Args:
        resume: The candidate's parsed resume.
        job: The job posting being applied to.
        score: The fit assessment from score_match.

    Returns:
        CoverLetter with 3 body paragraphs grounded in resume evidence.
    """
    user_prompt = f"""Write a tailored cover letter for this candidate applying to this job.

{_format_resume(resume)}

---

{_format_job(job)}

---

{_format_score(score)}

---

Return a structured CoverLetter following the rules above. Remember: open with
concrete evidence (a project name, an award, a real shipped system), never
amplify "(basics)" skills, no empty intensifiers, closing must connect a real
candidate strength to a specific company need.
"""
    return await structured_complete(
        schema=CoverLetter,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
