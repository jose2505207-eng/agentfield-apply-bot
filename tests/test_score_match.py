"""
Smoke test for score_match.

Strategy: parse Jose's resume, then score against TWO contrasting jobs:
  1. GOOD-FIT: AI Product Engineer role at a startup. Should score high.
  2. POOR-FIT: Senior Java Backend at a bank. Should score low.

Why two jobs? A scorer that gives the same score to everything is useless.
This test verifies the scorer actually DISCRIMINATES between fit levels.

Run with:
  python -m tests.test_score_match

Cost: ~$0.003 with gpt-4o-mini (3 LLM calls: 1 parse_resume + 2 score_match).
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reasoners.parse_resume import parse_resume
from src.reasoners.score_match import score_match
from src.schemas.job import JobPosting


# ============================================================================
# Test fixtures: two hand-crafted jobs that should score very differently.
# ============================================================================

GOOD_FIT_JOB = JobPosting(
    id="sample-good-001",
    url="https://example.com/jobs/ai-engineer",
    source="sample",
    title="AI Product Engineer",
    company="ExampleAI",
    description="""We're a Series A startup building autonomous AI agents for enterprise workflows.

What you'll do:
- Design and ship LLM-powered features in production
- Build agent pipelines using OpenAI, Anthropic, and emerging frameworks
- Work with TypeScript and Python across the stack
- Own features end-to-end: from spec to deploy
- Collaborate with a small team of senior engineers

Requirements:
- 2+ years building production software
- Hands-on experience with LLM APIs (OpenAI, Anthropic, etc.)
- Proficiency in Python OR TypeScript
- You've actually shipped agentic systems, not just experimented

Nice to have:
- Experience with Supabase, Postgres
- Background in workflow automation tools (n8n, Zapier, etc.)
- Bilingual (English/Spanish) for our LATAM users

We move fast and ship daily. Looking for builders who deploy, not just demo.""",
    location="Remote (US/LATAM)",
    is_remote=True,
    salary_min=120000,
    salary_max=160000,
    salary_currency="USD",
    equity_offered=True,
    required_skills=["Python", "TypeScript", "LLM APIs", "Production deployment"],
    nice_to_have_skills=["Supabase", "n8n", "Spanish"],
    years_experience_required=2,
    visa_sponsorship=None,
    employment_type="full_time",
    posted_date="2026-05-01",
    apply_method="external",
)


POOR_FIT_JOB = JobPosting(
    id="sample-poor-001",
    url="https://example.com/jobs/senior-java",
    source="sample",
    title="Senior Java Backend Engineer",
    company="LegacyBank Corp",
    description="""Senior backend engineer for our core banking platform.

Required:
- 8+ years of Java development
- Deep expertise in Spring Boot, Hibernate, Kafka
- Experience with high-throughput transactional systems (1M+ TPS)
- Strong background in financial systems, regulatory compliance (SOX, PCI-DSS)
- Lead experience: mentored 5+ engineers
- On-call rotation expected

Nice to have:
- Kotlin
- AWS / Kubernetes / Terraform infrastructure
- Master's degree in CS or related

This is an in-office role, no remote. Based in Charlotte, NC.""",
    location="Charlotte, NC",
    is_remote=False,
    salary_min=180000,
    salary_max=240000,
    salary_currency="USD",
    equity_offered=False,
    required_skills=["Java", "Spring Boot", "Hibernate", "Kafka", "Financial systems"],
    nice_to_have_skills=["Kotlin", "AWS", "Kubernetes"],
    years_experience_required=8,
    visa_sponsorship=None,
    employment_type="full_time",
    posted_date="2026-05-01",
    apply_method="external",
)


async def main():
    resume_pdf = os.getenv(
        "TEST_RESUME_PDF",
        str(Path.home() / "Downloads" / "Jose_Zaragoza_Resume_Versatile.pdf"),
    )

    print(f"Parsing resume: {resume_pdf}")
    resume = await parse_resume(resume_pdf)
    print(f"Resume parsed for: {resume.full_name}\n")

    for label, job in [("GOOD-FIT", GOOD_FIT_JOB), ("POOR-FIT", POOR_FIT_JOB)]:
        print(f"=== {label}: {job.title} @ {job.company} ===")
        result = await score_match(resume, job)

        print(f"  Score:    {result.score}/100")
        print(f"  Verdict:  {result.verdict.upper()}")
        print(f"  Reasoning: {result.reasoning}")
        print(f"\n  Matching skills ({len(result.matching_skills)}):")
        for s in result.matching_skills:
            print(f"    + {s}")
        print(f"\n  Missing skills ({len(result.missing_skills)}):")
        for s in result.missing_skills:
            print(f"    - {s}")
        if result.strengths:
            print(f"\n  Strengths:")
            for s in result.strengths:
                print(f"    + {s}")
        if result.concerns:
            print(f"\n  Concerns:")
            for c in result.concerns:
                print(f"    - {c}")
        print()

    print("✓ Smoke test complete.")
    print("  Eyeball check: GOOD-FIT should score >70 (apply), POOR-FIT should score <50 (skip).")
    print("  If both score similarly, the prompt or rubric needs work.")


if __name__ == "__main__":
    asyncio.run(main())
