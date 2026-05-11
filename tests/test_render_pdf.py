"""
Smoke test for render_pdf.

Full end-to-end:
  1. Parse Jose's resume
  2. Fetch real jobs
  3. Score and pick top match
  4. Tailor resume
  5. Generate cover letter
  6. Render BOTH to PDF on disk
  7. Verify files exist and have non-trivial size

Run with:
  python -m tests.test_render_pdf

Cost: ~$0.015 (parse + 6 scores + 1 tailor + 1 cover letter) plus PDF rendering
which is free.

Output:
  output/Jose_Zaragoza__cover_letter.pdf
  output/Jose_Zaragoza__tailored_resume.pdf
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
from src.reasoners.search_jobs import search_jobs
from src.reasoners.score_match import score_match
from src.reasoners.tailor_cover_letter import tailor_cover_letter
from src.reasoners.tailor_resume import tailor_resume
from src.render.render_pdf import render_cover_letter_pdf, render_resume_pdf


async def main():
    resume_pdf = os.getenv(
        "TEST_RESUME_PDF",
        str(Path.home() / "Downloads" / "Jose_Zaragoza_Resume_Versatile.pdf"),
    )
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    print(f"[1/6] Parsing resume...")
    resume = await parse_resume(resume_pdf)
    print(f"      OK: {resume.full_name}\n")

    print(f"[2/6] Fetching jobs...")
    jobs = await search_jobs("engineer python", sources=["remoteok"], max_per_source=10)
    if not jobs:
        print("      No jobs returned. Try a different query.")
        return
    print(f"      OK: {len(jobs)} jobs\n")

    print(f"[3/6] Scoring jobs...")
    scored = []
    for job in jobs:
        score = await score_match(resume, job)
        scored.append((score, job))
        print(f"      {score.score:3d}/100  {job.title[:55]}")
    scored.sort(key=lambda x: x[0].score, reverse=True)
    top_score, top_job = scored[0]
    print(f"\n      Top: {top_job.title} @ {top_job.company} ({top_score.score}/100)\n")

    print(f"[4/6] Tailoring resume...")
    tailored, violations = await tailor_resume(resume, top_job, top_score)
    print(f"      OK ({len(tailored.changes_made)} bullets rewritten, "
          f"{len(violations)} violations corrected)\n")

    print(f"[5/6] Generating cover letter...")
    letter = await tailor_cover_letter(resume, top_job, top_score)
    print(f"      OK ({len(letter.body_paragraphs)} paragraphs, "
          f"{len(letter.key_evidence_used)} evidence items)\n")

    print(f"[6/6] Rendering PDFs...")
    safe_name = resume.full_name.replace(" ", "_")
    cover_path = render_cover_letter_pdf(
        letter,
        tailored,  # use tailored for matching contact info
        output_dir / f"{safe_name}__cover_letter.pdf",
    )
    resume_path = render_resume_pdf(
        tailored,
        output_dir / f"{safe_name}__tailored_resume.pdf",
    )
    print(f"      OK\n")

    # === Verification ===
    print("=" * 60)
    print("OUTPUT FILES")
    print("=" * 60)
    for label, path in [("Cover letter", cover_path), ("Tailored resume", resume_path)]:
        if path.exists():
            size_kb = path.stat().st_size / 1024
            print(f"  ✓ {label}: {path}  ({size_kb:.1f} KB)")
            assert size_kb > 1, f"{label} PDF is suspiciously small ({size_kb:.1f} KB)"
        else:
            print(f"  ✗ {label}: file NOT FOUND at {path}")
            raise FileNotFoundError(path)

    print("\n--- Eyeball checklist ---")
    print(f"  1. Open {cover_path}")
    print(f"     - Header (name + contact) on top right")
    print(f"     - Date below header")
    print(f"     - Greeting → 3 paragraphs → sign-off")
    print(f"     - Single accent color (navy), sans-serif throughout")
    print(f"  2. Open {resume_path}")
    print(f"     - Name big, contact info compact below")
    print(f"     - Sections: Summary, Experience, Projects, Skills, Education, Awards, Languages")
    print(f"     - Skills marked '(basics)' should appear AT THE END of their category,")
    print(f"       not at the front (verifies the marginal filter merge-back worked)")
    print(f"  3. Check for layout issues: orphaned headers, text running off page, missing fields")


if __name__ == "__main__":
    asyncio.run(main())
