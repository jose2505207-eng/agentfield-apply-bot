"""
Smoke test for tailor_cover_letter (v2 prompt).

Stricter checks reflecting the v2 prompt's higher bar:
  - Hook must NOT start with banned generic phrases
  - Banlist of empty intensifiers expanded
  - Marginal skills (Docker, etc.) should not appear as core claims

Run with:
  python -m tests.test_tailor_cover_letter

Cost: ~$0.005 with gpt-4o-mini.
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


# Hook openers that betray a generic letter. The first paragraph must NOT
# start with any of these. Lowercase comparison.
BANNED_HOOK_OPENERS = [
    "i am applying for",
    "i am writing to",
    "i would like to apply",
    "your role caught my attention",
    "with a strong background",
    "as an experienced",
    "i am excited to",
    "i am thrilled to",
    "as a passionate",
]

# Empty intensifiers that should not appear anywhere in the letter.
BANNED_INTENSIFIERS = [
    "showcasing my ability",
    "demonstrating my capability",
    "highlighting my skills",
    "leveraging my expertise",
    "bringing value through",
    "passionate about",
    "excited to",
    "team player",
    "proven track record",
    "results-oriented",
    "would love the opportunity",
    "synergies",
    "value-add",
]

# Words that signal we kept generating the standard "I am applying for" letter.
LAZY_INTROS = [
    "i am applying for",
    "i am writing",
    "your posting",
]


async def main():
    resume_pdf = os.getenv(
        "TEST_RESUME_PDF",
        str(Path.home() / "Downloads" / "Jose_Zaragoza_Resume_Versatile.pdf"),
    )

    print(f"[1/4] Parsing resume...")
    resume = await parse_resume(resume_pdf)
    print(f"      OK: {resume.full_name}\n")

    print(f"[2/4] Fetching real jobs from RemoteOK...")
    jobs = await search_jobs("engineer python", sources=["remoteok"], max_per_source=10)
    if not jobs:
        print("      No jobs returned. Try a different query and rerun.")
        return
    print(f"      OK: {len(jobs)} jobs fetched.\n")

    print(f"[3/4] Scoring {len(jobs)} jobs...")
    scored = []
    for job in jobs:
        score = await score_match(resume, job)
        scored.append((score, job))
        print(f"      {score.score:3d}/100  {score.verdict:10s}  {job.title[:60]}")
    scored.sort(key=lambda x: x[0].score, reverse=True)
    top_score, top_job = scored[0]
    print(f"\n      Top match: {top_job.title} @ {top_job.company}  ({top_score.score}/100)\n")

    print(f"[4/4] Generating cover letter (v2 prompt)...")
    letter = await tailor_cover_letter(resume, top_job, top_score)
    print(f"      OK\n")

    # === Display the letter ===
    print("=" * 70)
    print(f"SUBJECT: {letter.subject}")
    print("=" * 70)
    print()
    print(letter.greeting)
    print()
    for i, para in enumerate(letter.body_paragraphs, 1):
        print(f"[Paragraph {i}]")
        print(para)
        print()
    print(letter.sign_off)
    print()
    print("=" * 70)
    print(f"Tone declared:        {letter.tone}")
    print(f"Evidence cited ({len(letter.key_evidence_used)}):")
    for ev in letter.key_evidence_used:
        print(f"  - {ev}")
    print("=" * 70)

    # === Quality assertions ===
    print("\n--- Quality checks ---")

    # 1. Three paragraphs exactly
    assert len(letter.body_paragraphs) == 3, (
        f"Expected 3 body paragraphs, got {len(letter.body_paragraphs)}"
    )
    print(f"✓ Exactly 3 body paragraphs")

    # 2. At least 2 evidence items
    assert len(letter.key_evidence_used) >= 2, (
        f"Letter cites only {len(letter.key_evidence_used)} evidence items"
    )
    print(f"✓ At least 2 evidence items cited ({len(letter.key_evidence_used)})")

    # 3. Hook quality: P1 must not START with banned generic openers
    p1 = letter.body_paragraphs[0].lower().strip()
    failed_hook = [opener for opener in BANNED_HOOK_OPENERS if p1.startswith(opener)]
    if failed_hook:
        print(f"✗ HOOK FAILS: starts with banned opener {failed_hook[0]!r}")
        print(f"   First 80 chars: {letter.body_paragraphs[0][:80]!r}")
    else:
        print(f"✓ Hook does not use generic opener")

    # 4. No empty intensifiers anywhere in body
    full_body = " ".join(letter.body_paragraphs).lower()
    found_intensifiers = [phr for phr in BANNED_INTENSIFIERS if phr in full_body]
    if found_intensifiers:
        print(f"✗ Empty intensifiers found: {found_intensifiers}")
    else:
        print(f"✓ No empty intensifiers")

    # 5. Company name appears
    if top_job.company.lower() in (letter.greeting + " ".join(letter.body_paragraphs)).lower():
        print(f"✓ Company name appears in letter")
    else:
        print(f"✗ Company name MISSING — letter is generic")

    # 6. Marginal skill check: did the letter amplify any "(basics)" skill?
    # Walk skills sections, find anything tagged basics/beginner/etc.
    marginal_skills = []
    for cat in resume.skills:
        for item in cat.items:
            low = item.lower()
            if "(basics)" in low or "(beginner)" in low or "(self-study)" in low:
                # Extract just the skill name without the qualifier
                bare = item.split("(")[0].strip().lower()
                if len(bare) >= 3:
                    marginal_skills.append(bare)
    amplified = []
    for sk in marginal_skills:
        if sk in full_body:
            # Check if it appears in evidence_used too
            evidence_str = " ".join(letter.key_evidence_used).lower()
            if sk in evidence_str:
                amplified.append(sk)
    if amplified:
        print(f"⚠ Marginal skills appear as evidence: {amplified}")
        print(f"   These are listed as basics/self-study in the resume; review the letter.")
    else:
        print(f"✓ No marginal skills amplified into core claims")

    # 7. Word count
    word_count = sum(len(p.split()) for p in letter.body_paragraphs)
    print(f"\n  Word count: {word_count} (target ~200, hard cap ~280)")

    print("\n--- Eyeball check ---")
    print("  Read P1 above. Does it open with a CONCRETE FACT (project, award,")
    print("  shipped system) in the first 12 words? Or does it sound generic?")
    print("\n  Read P3. Does it tie YOUR strength to THEIR specific need? Or does")
    print("  it just parrot their mission/tagline?")


if __name__ == "__main__":
    asyncio.run(main())
