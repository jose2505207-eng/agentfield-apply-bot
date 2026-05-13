"""
Smoke test for the Actionbook wrapper and CandidateProfile loading.

PATCHED for Actionbook v0.4.2: extension status uses `actionbook extension
status` (does NOT require a session), and the live test uses
start_session(open_url=...) which returns a BrowserSession with both
session_id and tab_id.

Run with:
  python -m tests.test_actionbook_client

What it checks:
  1. data/profile.json exists and parses into CandidateProfile.
  2. Profile has no FILL_ME placeholders remaining.
  3. `actionbook extension status` reports the bridge state.
  4. (Live, optional) start a session, open google.com, snapshot it,
     screenshot it, read its URL.

Skip the live part with SKIP_LIVE=1.
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

from src.adapters.browser.actionbook_client import (
    ActionbookClient,
    ActionbookError,
    BrowserSession,
)
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
    raw.pop("_README", None)
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
    # 3. Actionbook extension reachable
    # ---------------------------------------------------------------
    print("[3/4] Checking Actionbook extension status (does not need a session)...")
    ab = ActionbookClient()
    try:
        status_out = await ab.extension_status()
        print("      OK: actionbook responded")
        print("      ─── extension status ───")
        for line in status_out.strip().splitlines():
            print(f"      {line}")
        print("      ────────────────────────")
        # Soft check: warn if the bridge isn't listening.
        if "bridge: not_listening" in status_out:
            print(
                "      WARN: bridge: not_listening. Run "
                "`actionbook browser start --mode local "
                "--set-session-id s1 --open-url https://www.google.com` "
                "to wake it up, then re-run this test."
            )
    except FileNotFoundError:
        print("      FAIL: `actionbook` not on PATH. Install per actionbook.dev/docs.")
        sys.exit(1)
    except ActionbookError as e:
        print(f"      WARN: actionbook returned non-zero. stderr:")
        print(f"      {e.stderr[:300]}")

    # ---------------------------------------------------------------
    # 4. Live smoke (optional)
    # ---------------------------------------------------------------
    if os.getenv("SKIP_LIVE") == "1":
        print("[4/4] Skipping live test (SKIP_LIVE=1)")
        print("\nAll non-live checks passed.")
        return

    print("[4/4] Live smoke test — start session, snapshot, screenshot...")
    try:
        browser_mode = os.getenv("ACTIONBOOK_MODE", "local")
        sess: BrowserSession = await ab.start_session(
            session_id="agentfield-smoke",
            open_url="https://www.google.com",
            mode=browser_mode,
        )
        print(f"      mode: {browser_mode}   session_id: {sess.session_id}   tab_id: {sess.tab_id}")

        await ab.wait(2.0)  # let the page settle before snapshotting
        snap = await ab.snapshot(session=sess.session_id, tab=sess.tab_id)
        print(f"      snapshot OK ({len(snap)} chars). First 400:")
        print("      ─── snapshot (head) ───")
        for line in snap[:400].splitlines():
            print(f"      {line}")
        print("      ───────────────────────")

        out_path = await ab.screenshot(
            "/tmp/actionbook_smoke.png",
            session=sess.session_id, tab=sess.tab_id,
        )
        print(f"      screenshot saved: {out_path}")

        url = await ab.current_url(session=sess.session_id, tab=sess.tab_id)
        print(f"      current_url: {url}")

        print("\nAll checks passed. You're ready for apply_to_job.")
    except ActionbookError as e:
        print(f"\nLive test failed:")
        print(f"  cmd:    {e.cmd}")
        print(f"  stderr: {e.stderr}")
        print("\nMost likely fixes:")
        print("  - Make sure the Chrome extension is installed and connected")
        print("  - Make sure your Chrome browser is open")
        print("  - Run `actionbook extension status` and confirm bridge is listening")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
