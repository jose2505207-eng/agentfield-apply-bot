"""
Smoke test for parse_resume.

Run with:
  python -m tests.test_parse_resume

This makes ONE real OpenAI call (~$0.001 with gpt-4o-mini).
"""
from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Add project root to path so `src` imports work when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reasoners.parse_resume import parse_resume


async def main():
    # Path to the resume PDF — adjust to your actual location
    resume_pdf = os.getenv(
        "TEST_RESUME_PDF",
        str(Path.home() / "Downloads" / "Jose_Zaragoza_Resume_Versatile.pdf"),
    )

    print(f"Parsing: {resume_pdf}")
    result = await parse_resume(resume_pdf)

    # Basic sanity checks
    assert result.full_name, "full_name should not be empty"
    assert result.summary, "summary should not be empty"
    assert len(result.experience) > 0, "should extract at least one experience"

    # Print a summary so you can eyeball quality
    print("\n=== PARSE RESULT ===")
    print(f"Name:     {result.full_name}")
    print(f"Email:    {result.email}")
    print(f"Location: {result.location}")
    print(f"LinkedIn: {result.linkedin_url}")
    print(f"GitHub:   {result.github_url}")
    print(f"\nSummary ({len(result.summary)} chars):")
    print(f"  {result.summary[:200]}{'...' if len(result.summary) > 200 else ''}")

    print(f"\nExperience: {len(result.experience)} entries")
    for exp in result.experience:
        print(f"  - {exp.title} @ {exp.company}  ({exp.start_date} – {exp.end_date})")
        print(f"    {len(exp.bullets)} bullets")

    print(f"\nProjects: {len(result.projects)} entries")
    for proj in result.projects:
        print(f"  - {proj.name}")
        print(f"    stack: {', '.join(proj.stack[:6])}")

    print(f"\nEducation: {len(result.education)} entries")
    for edu in result.education:
        print(f"  - {edu.degree} @ {edu.institution}")

    print(f"\nSkills categories: {[s.name for s in result.skills]}")
    for cat in result.skills:
        print(f"  {cat.name}: {', '.join(cat.items[:6])}{'...' if len(cat.items) > 6 else ''}")
    print(f"\nLanguages: {result.languages}")
    print(f"Awards: {result.awards}")

    print("\n✓ All assertions passed")


if __name__ == "__main__":
    asyncio.run(main())
