"""
Smoke test for the Actionbook wrapper and CandidateProfile loading.

Run with:
  python -m tests.test_actionbook_client

What it checks (does NOT cost LLM tokens; minimal cost from Actionbook):
  1. `actionbook` binary is on PATH and responds.
  2. data/profile.json exists and parses into CandidateProfile.
  3. Profile has no FILL_ME placeholders remaining.
  4. (Live, optional) start a session, open google.com, snapshot it, screenshot it.

Skip the live part by setting SKIP_LIVE=1.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.browser.actionbook_client import ActionbookClient, ActionbookError
from src.schemas.candidate_profile import CandidateProfile


PROFILE_PATH = Path("data/profile.json")


async def main():
    # ---------------------------------------------------------------
    # 1. Profile loads
    # ---------------------------------------------------------------
    print("[1/4] Loading CandidateProfile from data/profile.json...")
    if not PROFILE_PATH.exists():
        print(f"      FAIL: {PROFILE_PATH} does not exist.")
        print(f"      Copy data/profile.template.json to data/profile.json and edit it.")
        sys.exit(1)

    raw = json.loads(PROFILE_PATH.read_text())
    raw.pop("_README", None)  # template's instructional key
    profile = CandidateProfile.model_validate(raw)
    print(f"      OK: profile loaded for {profile.full_name}")

    # ---------------------------------------------------------------
    # 2. No unfilled placeholders
    # ---------------------------------------------------------------
    print("[2/4] Checking for unfilled placeholders...")
    bad = profile.has_unfilled_placeholders()
    if bad:
        print(f"      FAIL: these fields still hold placeholder values: {bad}")
        sys.exit(1)
    print("      OK: no placeholders remaining")

    # ---------------------------------------------------------------
    # 3. Actionbook CLI reachable
    # ---------------------------------------------------------------
    print("[3/4] Checking Actionbook CLI...")
    ab = ActionbookClient()
    try:
        status_out = await ab.status()
        print("      OK: actionbook responded")
        print(f"      status output (first 300 chars): {status_out[:300].strip()}")
    except FileNotFoundError:
        print("      FAIL: `actionbook` not on PATH. Install per actionbook.dev/docs.")
        sys.exit(1)
    except ActionbookError as e:
        # Non-zero exit could just mean "no session running yet" — still useful info.
        print(f"      WARN: actionbook returned non-zero. stderr was:")
        print(f"      {e.stderr[:300]}")
        print("      This may be OK if 'no active session' — continuing.")

    # ---------------------------------------------------------------
    # 4. Live smoke (optional)
    # ---------------------------------------------------------------
    if os.getenv("SKIP_LIVE") == "1":
        print("[4/4] Skipping live test (SKIP_LIVE=1)")
        print("\nAll non-live checks passed.")
        return

    print("[4/4] Live smoke test — opening google.com, snapshotting, screenshotting...")
    try:
        session = await ab.start_session()
        print(f"      session: {session}")

        await ab.open("https://www.google.com", session=session)
        await asyncio.sleep(2)

        snap = await ab.snapshot(session=session)
        print(f"      snapshot OK ({len(snap)} chars). First 200:")
        print(f"      {snap[:200].strip()}")

        out_path = await ab.screenshot("/tmp/actionbook_smoke.png", session=session)
        print(f"      screenshot saved: {out_path}")

        url = await ab.current_url(session=session)
        print(f"      current_url: {url}")

        print("\nAll checks passed. You're ready for apply_to_job.")
    except ActionbookError as e:
        print(f"\nLive test failed:")
        print(f"  cmd:    {e.cmd}")
        print(f"  stderr: {e.stderr}")
        print("\nMost likely fixes:")
        print("  - Make sure the Chrome extension is installed and connected")
        print("  - Make sure your Chrome browser is open")
        print("  - Re-run `actionbook browser start` manually to see verbose errors")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
