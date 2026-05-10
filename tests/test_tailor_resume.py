"""
Smoke test for tailor_resume.

Strategy: full pipeline integration.
  1. Parse Jose's resume.
  2. Fetch real RemoteOK jobs.
  3. Score them and pick the top match.
  4. Tailor the resume to that job.
  5. Audit the changes.

Run with:
  python -m tests.test_tailor_resume

Cost: ~$0.01 with gpt-4o-mini (parse + 6 scores + 1 tailor; tailor is the
expensive call because the output is large).
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
from src.reasoners.tailor_resume import tailor_resume


# Verbs that signal inflation. If a rewrite uses one of these but the
# original didn't, that's a red flag.
INFLATION_VERBS = ["led", "owned", "architected", "spearheaded", "drove", "pioneered"]


async def main():
    resume_pdf = os.getenv(
        "TEST_RESUME_PDF",
        str(Path.home() / "Downloads" / "Jose_Zaragoza_Resume_Versatile.pdf"),
    )

    print(f"[1/4] Parsing resume...")
    original = await parse_resume(resume_pdf)
    print(f"      OK: {original.full_name}\n")

    print(f"[2/4] Fetching real jobs...")
    jobs = await search_jobs("ai engineer python", sources=["remoteok"], max_per_source=10)
    if not jobs:
        print("      No jobs returned. Try a different query.")
        return
    print(f"      OK: {len(jobs)} jobs.\n")

    print(f"[3/4] Scoring {len(jobs)} jobs...")
    scored = []
    for job in jobs:
        score = await score_match(original, job)
        scored.append((score, job))
        print(f"      {score.score:3d}/100  {score.verdict:10s}  {job.title[:60]}")
    scored.sort(key=lambda x: x[0].score, reverse=True)
    top_score, top_job = scored[0]
    print(f"\n      Top match: {top_job.title} @ {top_job.company}  ({top_score.score}/100)\n")

    print(f"[4/4] Tailoring resume to top job...")
    tailored, violations = await tailor_resume(original, top_job, top_score)
    print(f"      OK\n")

    # === Identity check ===
    print("=" * 70)
    print(f"IDENTITY (must be unchanged)")
    print("=" * 70)
    print(f"  Name:    {tailored.full_name}  {'✓' if tailored.full_name == original.full_name else '✗'}")
    print(f"  Email:   {tailored.email}      {'✓' if tailored.email == original.email else '✗'}")
    print(f"  GitHub:  {tailored.github_url} {'✓' if tailored.github_url == original.github_url else '✗'}")

    # === Summary diff ===
    print(f"\n=== SUMMARY ===")
    print(f"\n[ORIGINAL]")
    print(f"  {original.summary}")
    print(f"\n[TAILORED]")
    print(f"  {tailored.summary}")

    # === Changes audit ===
    print(f"\n{'=' * 70}")
    print(f"CHANGES MADE ({len(tailored.changes_made)} bullets rewritten, {tailored.bullets_kept_unchanged} kept)")
    print(f"{'=' * 70}")
    for i, ch in enumerate(tailored.changes_made, 1):
        print(f"\n  Change {i} — {ch.section}")
        print(f"  ORIGINAL:  {ch.original}")
        print(f"  REWRITTEN: {ch.rewritten}")
        print(f"  WHY:       {ch.rationale}")

    # === Skills order check ===
    print(f"\n=== SKILLS REORDERING ===")
    for orig_cat, new_cat in zip(original.skills, tailored.skills):
        if orig_cat.items != new_cat.items:
            print(f"\n  Category: {orig_cat.name}")
            print(f"  ORIGINAL ORDER: {orig_cat.items}")
            print(f"  NEW ORDER:      {new_cat.items}")
            # Check no items added/removed
            added = set(new_cat.items) - set(orig_cat.items)
            removed = set(orig_cat.items) - set(new_cat.items)
            if added:
                print(f"  ✗ ADDED skills (not allowed!): {added}")
            if removed:
                print(f"  ✗ REMOVED skills (not allowed!): {removed}")

    # === Violations from post-validation ===
    print(f"\n{'=' * 70}")
    if violations:
        print(f"⚠ POST-VALIDATION CORRECTIONS ({len(violations)})")
        print(f"{'=' * 70}")
        for v in violations:
            print(f"  - {v}")
        print(f"\n  These are immutable-field violations the LLM produced and we restored.")
        print(f"  If this list is non-empty, the prompt is drifting and should be tightened.")
    else:
        print(f"✓ No post-validation corrections needed (LLM respected all immutable fields)")

    # === Inflation check ===
    print(f"\n--- Inflation check ---")
    inflation_flags = []
    for ch in tailored.changes_made:
        orig_low = ch.original.lower()
        new_low = ch.rewritten.lower()
        for verb in INFLATION_VERBS:
            if verb in new_low and verb not in orig_low:
                inflation_flags.append((ch.section, verb, ch.original, ch.rewritten))
    if inflation_flags:
        print(f"⚠ {len(inflation_flags)} possible inflations detected:")
        for section, verb, orig, new in inflation_flags:
            print(f"  - {section}: added {verb!r}")
            print(f"      orig: {orig}")
            print(f"      new:  {new}")
    else:
        print(f"✓ No inflation verbs added in rewrites")

    print(f"\n--- Eyeball checklist ---")
    print(f"  1. Read each REWRITTEN bullet vs its ORIGINAL above. Same scope?")
    print(f"  2. Read the new SUMMARY. Same person? Or does it sound bigger?")
    print(f"  3. Look at SKILLS REORDERING. Job-relevant skills moved to front?")


if __name__ == "__main__":
    asyncio.run(main())
