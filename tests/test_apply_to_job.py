"""
Tests for apply_to_job — control-flow coverage with mocks.

PATCHED for Actionbook v0.4.2 API: start_session returns BrowserSession,
every browser command takes both session and tab.

RUN:
  python -m tests.test_apply_to_job

  # Optional live end-to-end (requires Actionbook + OPENAI_API_KEY + a real URL)
  LIVE=1 APPLY_TEST_URL='https://jobs.lever.co/<co>/<role-id>/apply' \\
      python -m tests.test_apply_to_job
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reasoners import apply_to_job as atj_module
from src.reasoners.apply_to_job import apply_to_job
from src.schemas.action_decision import ActionDecision
from src.schemas.apply_result import ApplyResult
from src.schemas.candidate_profile import CandidateProfile
from src.schemas.cover_letter import CoverLetter
from src.schemas.job import JobPosting
from src.adapters.browser.actionbook_client import BrowserSession
from src.utils import application_history


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def make_profile(*, name: str = "Jose Test", placeholder: bool = False) -> CandidateProfile:
    return CandidateProfile(
        full_name="FILL_ME — name" if placeholder else name,
        email="jose@test.example",
        phone="+1 555 000 0000",
        location_city="Sunnyvale",
        location_state="CA",
        location_country="US",
        linkedin_url=None,
        github_url=None,
        portfolio_url=None,
        work_auth_status="us_citizen",
        requires_visa_sponsorship_now_or_future=False,
    )


def make_job(*, job_id: str = "job-1", source: str = "remoteok") -> JobPosting:
    return JobPosting(
        id=job_id,
        url="https://example.com/apply",
        source=source,
        title="AI Engineer",
        company="ExampleCo",
        description="We build agents.",
        location="Remote",
        is_remote=True,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        equity_offered=None,
        required_skills=[],
        nice_to_have_skills=[],
        years_experience_required=None,
        visa_sponsorship=None,
        employment_type="full_time",
        posted_date=None,
        apply_method="external",
    )


def make_cover_letter() -> CoverLetter:
    return CoverLetter(
        subject="Application for AI Engineer at ExampleCo",
        greeting="Dear Hiring Team at ExampleCo,",
        body_paragraphs=[
            "Hook paragraph mentioning ExampleCo specifically.",
            "Evidence paragraph with concrete resume facts.",
            "Closing paragraph with availability.",
        ],
        sign_off="Sincerely,\nJose Test",
        tone="formal",
        key_evidence_used=["AI Fair award", "production GPT-4o pipeline"],
    )


# ----------------------------------------------------------------------
# Mock ActionbookClient — implements the v0.4.2 async surface, no subprocess
# ----------------------------------------------------------------------


class MockActionbookClient:
    """Stand-in for ActionbookClient.

    Records calls (name, args, kwargs) so tests can assert what got executed.
    Returns canned snapshots cycled in order. Every browser method takes
    both session and tab kwargs, matching the real client post-patch.
    """

    def __init__(
        self,
        *,
        snapshots: Optional[list[str]] = None,
        session_id: str = "agentfield",
        tab_id: str = "t1",
    ):
        self._snapshots = snapshots or ["[default mock snapshot]"]
        self._snap_idx = 0
        self._session_id = session_id
        self._tab_id = tab_id
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.append((name, args, kwargs))

    async def start_session(
        self,
        *,
        session_id: str = "agentfield",
        open_url: Optional[str] = None,
        mode: str = "extension",
    ) -> BrowserSession:
        self._record("start_session", (), {
            "session_id": session_id, "open_url": open_url, "mode": mode,
        })
        return BrowserSession(
            session_id=self._session_id, tab_id=self._tab_id,
        )

    async def open(self, url: str, *, session: str, tab: str) -> None:
        self._record("open", (url,), {"session": session, "tab": tab})

    async def goto(self, url: str, *, session: str, tab: str) -> None:
        self._record("goto", (url,), {"session": session, "tab": tab})

    async def snapshot(
        self,
        *,
        session: str,
        tab: str,
        interactive: bool = True,
        compact: bool = True,
    ) -> str:
        self._record("snapshot", (), {
            "session": session, "tab": tab,
            "interactive": interactive, "compact": compact,
        })
        idx = min(self._snap_idx, len(self._snapshots) - 1)
        self._snap_idx += 1
        return self._snapshots[idx]

    async def click(self, ref: str, *, session: str, tab: str) -> None:
        self._record("click", (ref,), {"session": session, "tab": tab})

    async def fill(self, ref: str, value: str, *, session: str, tab: str) -> None:
        self._record("fill", (ref, value), {"session": session, "tab": tab})

    async def select(self, ref: str, value: str, *, session: str, tab: str) -> None:
        self._record("select", (ref, value), {"session": session, "tab": tab})

    async def upload(self, ref: str, path: str, *, session: str, tab: str) -> None:
        self._record("upload", (ref, path), {"session": session, "tab": tab})

    async def scroll(
        self, direction: str = "down", *, session: str, tab: str,
    ) -> None:
        self._record("scroll", (direction,), {"session": session, "tab": tab})

    async def screenshot(
        self, output_path: str, *, session: str, tab: str,
    ) -> str:
        self._record("screenshot", (output_path,), {
            "session": session, "tab": tab,
        })
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        return str(p.resolve())

    async def eval_js(
        self, expression: str, *, session: str, tab: str,
    ) -> str:
        self._record("eval_js", (expression,), {
            "session": session, "tab": tab,
        })
        return ""

    async def current_url(self, *, session: str, tab: str) -> str:
        return "https://example.com/apply"

    async def wait(self, seconds: float) -> None:
        self._record("wait", (seconds,), {})


# ----------------------------------------------------------------------
# Helpers to script the LLM's behavior
# ----------------------------------------------------------------------


def queue_llm(decisions: list[ActionDecision]):
    queue = list(decisions)

    async def fake_structured_complete(*, schema, system, user, **kwargs):
        if not queue:
            raise AssertionError(
                "test queued no more decisions but the loop asked for one."
            )
        return queue.pop(0)

    return fake_structured_complete


def patch_llm(decisions: list[ActionDecision]) -> None:
    atj_module.structured_complete = queue_llm(decisions)  # type: ignore[assignment]


# ----------------------------------------------------------------------
# Tracker
# ----------------------------------------------------------------------


PASS = 0
FAIL = 0


def _ok(label: str) -> None:
    global PASS
    PASS += 1
    print(f"  ✅ {label}")


def _fail(label: str, reason: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  ❌ {label}\n        {reason}")


def _check(label: str, cond: bool, reason: str = "") -> None:
    if cond:
        _ok(label)
    else:
        _fail(label, reason or "assertion failed")


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


async def test_dedup_short_circuit(tmpdir: Path) -> None:
    print("\n[test] dedup short-circuit on already-applied job")
    history_path = tmpdir / "applications.json"

    job = make_job(job_id="dup-1")
    seed = ApplyResult(
        job_id=job.id,
        job_source=job.source,
        job_title=job.title,
        company=job.company,
        apply_url=job.url,
        success=True,
        method_used="actionbook_form",
        dry_run=False,
        steps_taken=5,
    )
    application_history.record_application(seed, history_path=history_path)

    client = MockActionbookClient()
    patch_llm([])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=job,
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'duplicate'", result.method_used == "duplicate",
           f"got {result.method_used}")
    _check("no actionbook calls were made", len(client.calls) == 0,
           f"calls={[c[0] for c in client.calls]}")
    _check("success == True (dup of success counts)", result.success is True)


async def test_preflight_placeholder_profile(tmpdir: Path) -> None:
    print("\n[test] preflight: profile has FILL_ME placeholder")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient()
    patch_llm([])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="prefl-1"),
        profile=make_profile(placeholder=True),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'preflight_failed'",
           result.method_used == "preflight_failed",
           f"got {result.method_used}")
    _check("success == False", result.success is False)
    _check("error mentions placeholder",
           "placeholder" in (result.error_message or "").lower(),
           f"error_message={result.error_message!r}")
    _check("no actionbook calls", len(client.calls) == 0)


async def test_preflight_missing_resume_pdf(tmpdir: Path) -> None:
    print("\n[test] preflight: resume PDF does not exist")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient()
    patch_llm([])

    result = await apply_to_job(
        job=make_job(job_id="prefl-2"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=tmpdir / "does_not_exist.pdf",
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'preflight_failed'",
           result.method_used == "preflight_failed",
           f"got {result.method_used}")
    _check("no actionbook calls", len(client.calls) == 0)


async def test_dry_run_intercepts_submit(tmpdir: Path) -> None:
    print("\n[test] happy dry-run: fill → fill → submit (intercepted)")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(
        snapshots=[
            "[snap 1: name input @e1, email input @e2, submit button @e9]",
            "[snap 2: name filled, email input @e2, submit @e9]",
            "[snap 3: both filled, submit @e9]",
        ]
    )

    patch_llm([
        ActionDecision(
            kind="fill", ref="@e1", value="Jose Test",
            reasoning="name input is empty, fill from profile",
            confidence="high", is_terminal=False,
        ),
        ActionDecision(
            kind="fill", ref="@e2", value="jose@test.example",
            reasoning="email input is empty, fill from profile",
            confidence="high", is_terminal=False,
        ),
        ActionDecision(
            kind="submit", ref="@e9", value=None,
            reasoning="all required fields filled, click submit",
            confidence="high", is_terminal=False,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="dryrun-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review",
           f"got {result.method_used}")
    _check("dry_run flag forced to True", result.dry_run is True)
    _check("success == False (nothing was actually submitted)",
           result.success is False)
    _check("steps_taken == 3", result.steps_taken == 3,
           f"got {result.steps_taken}")
    _check("screenshot_path is set", result.screenshot_path is not None)

    submit_clicks = [
        c for c in client.calls if c[0] == "click" and c[1] == ("@e9",)
    ]
    _check("submit button was NOT clicked", len(submit_clicks) == 0,
           f"got {len(submit_clicks)} clicks on @e9")
    fills = [c for c in client.calls if c[0] == "fill"]
    _check("both fills were executed", len(fills) == 2,
           f"got {len(fills)} fills")

    # NEW: verify the calls pass BOTH session and tab
    for name, _args, kwargs in client.calls:
        if name in ("snapshot", "click", "fill", "select", "upload",
                    "scroll", "screenshot", "eval_js"):
            _check(
                f"{name} call passed session AND tab",
                "session" in kwargs and "tab" in kwargs,
                f"kwargs={kwargs}",
            )
            break  # one assertion is enough; all calls share the dispatcher


async def test_done_path_success(tmpdir: Path) -> None:
    print("\n[test] done path: confirmation page → success=True")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(
        snapshots=[
            "[snap: form already submitted, 'Application received' visible]",
        ]
    )

    patch_llm([
        ActionDecision(
            kind="done", ref=None, value=None,
            reasoning="confirmation banner 'Application received' is visible",
            confidence="high", is_terminal=True,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="done-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=False,
        confirm=True,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("success == True", result.success is True)
    _check("method_used == 'actionbook_form'",
           result.method_used == "actionbook_form")
    _check("steps_taken == 1", result.steps_taken == 1)


async def test_stuck_on_captcha(tmpdir: Path) -> None:
    print("\n[test] stuck path: LLM reports CAPTCHA")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(snapshots=["[snap: CAPTCHA visible]"])
    patch_llm([
        ActionDecision(
            kind="stuck", ref=None, value=None,
            reasoning="CAPTCHA challenge visible on page; cannot proceed",
            confidence="high", is_terminal=True,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="stuck-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review",
           f"got {result.method_used}")
    _check("error mentions CAPTCHA",
           "CAPTCHA" in (result.error_message or ""),
           f"error_message={result.error_message!r}")
    _check("success == False", result.success is False)


async def test_anti_loop_guard(tmpdir: Path) -> None:
    print("\n[test] anti-loop: same click 3x → manual_review")
    history_path = tmpdir / "applications.json"

    same = ActionDecision(
        kind="click", ref="@e1", value=None,
        reasoning="click the button",
        confidence="medium", is_terminal=False,
    )

    client = MockActionbookClient(snapshots=["s1", "s2", "s3", "s4"])
    patch_llm([same, same, same])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="loop-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review")
    _check("error mentions loop / repeated",
           "loop" in (result.error_message or "").lower()
           or "repeated" in (result.error_message or "").lower(),
           f"error_message={result.error_message!r}")


async def test_low_confidence_submit_blocked(tmpdir: Path) -> None:
    print("\n[test] low-confidence submit blocked")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(snapshots=["[snap: ambiguous form]"])
    patch_llm([
        ActionDecision(
            kind="submit", ref="@e9", value=None,
            reasoning="might be done? unsure if all required fields are filled",
            confidence="low", is_terminal=False,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="lowconf-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=False,
        confirm=True,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review",
           f"got {result.method_used}")
    submit_clicks = [
        c for c in client.calls if c[0] == "click" and c[1] == ("@e9",)
    ]
    _check("submit was NOT clicked", len(submit_clicks) == 0)


async def test_inconsistent_decision_rejected(tmpdir: Path) -> None:
    print("\n[test] inconsistent decision (kind=submit, is_terminal=True) rejected")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(snapshots=["[snap]"])
    patch_llm([
        ActionDecision(
            kind="submit", ref="@e9", value=None,
            reasoning="trying to submit",
            confidence="high", is_terminal=True,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="incons-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=False,
        confirm=True,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review")
    _check("error mentions inconsistent",
           "inconsistent" in (result.error_message or "").lower(),
           f"error_message={result.error_message!r}")


async def test_max_steps_exhaustion(tmpdir: Path) -> None:
    print("\n[test] max_steps exhausted without terminating")
    history_path = tmpdir / "applications.json"

    client = MockActionbookClient(snapshots=["s"] * 10)

    decisions = []
    for i in range(10):
        kind = "scroll" if i % 2 == 0 else "wait"
        decisions.append(ActionDecision(
            kind=kind,
            ref=None,
            value="1" if kind == "wait" else None,
            reasoning=f"step {i}: nothing actionable yet",
            confidence="medium", is_terminal=False,
        ))
    patch_llm(decisions)

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    result = await apply_to_job(
        job=make_job(job_id="timeout-1"),
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
        max_steps=3,
    )

    _check("method_used == 'manual_review'",
           result.method_used == "manual_review")
    _check("steps_taken == max_steps",
           result.steps_taken == 3, f"got {result.steps_taken}")
    _check("error mentions max_steps",
           "max_steps" in (result.error_message or ""),
           f"error_message={result.error_message!r}")
    # NEW: scroll was dispatched via the native scroll command
    scrolls = [c for c in client.calls if c[0] == "scroll"]
    _check("scroll used native command (not eval_js)",
           len(scrolls) >= 1, f"got {len(scrolls)} scrolls")


async def test_history_records_and_dedupes(tmpdir: Path) -> None:
    print("\n[test] history persists across runs and second call sees dedup")
    history_path = tmpdir / "applications.json"

    job = make_job(job_id="persist-1")

    client1 = MockActionbookClient(snapshots=["[confirmation]"])
    patch_llm([
        ActionDecision(
            kind="done", ref=None, value=None,
            reasoning="confirmation visible",
            confidence="high", is_terminal=True,
        ),
    ])

    resume_pdf = tmpdir / "resume.pdf"
    resume_pdf.write_bytes(b"%PDF-1.4 mock")

    r1 = await apply_to_job(
        job=job,
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=False,
        confirm=True,
        client=client1,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )
    _check("first run succeeded", r1.success is True
           and r1.method_used == "actionbook_form")

    import json as _json
    raw = _json.loads(history_path.read_text())
    _check("history file is a list", isinstance(raw, list))
    _check("history has 1 entry", len(raw) == 1)

    client2 = MockActionbookClient()
    patch_llm([])

    r2 = await apply_to_job(
        job=job,
        profile=make_profile(),
        cover_letter=make_cover_letter(),
        tailored_resume_pdf=resume_pdf,
        dry_run=True,
        confirm=False,
        client=client2,
        history_path=history_path,
        screenshot_dir=tmpdir / "shots",
    )
    _check("second run = duplicate",
           r2.method_used == "duplicate", f"got {r2.method_used}")
    _check("client2 untouched", len(client2.calls) == 0)
    raw2 = _json.loads(history_path.read_text())
    _check("history has 2 entries after second run",
           len(raw2) == 2, f"got {len(raw2)}")


# ----------------------------------------------------------------------
# Optional LIVE end-to-end test
# ----------------------------------------------------------------------


async def test_live_dry_run() -> None:
    """Real Chrome + real LLM + real URL. Enable with LIVE=1."""
    print("\n[test] LIVE dry-run end-to-end")
    url = os.environ.get("APPLY_TEST_URL")
    if not url:
        _fail("LIVE config", "set APPLY_TEST_URL to a real apply page")
        return

    from src.adapters.browser.actionbook_client import ActionbookClient

    job = JobPosting(
        id="live-test",
        url=url,
        source="manual",
        title="(test) AI Engineer",
        company="(test) live target",
        description="(test)",
        location=None,
        is_remote=True,
        salary_min=None, salary_max=None, salary_currency=None,
        equity_offered=None,
        required_skills=[], nice_to_have_skills=[],
        years_experience_required=None, visa_sponsorship=None,
        employment_type=None, posted_date=None, apply_method="external",
    )

    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        resume_pdf = td_p / "resume.pdf"
        resume_pdf.write_bytes(b"%PDF-1.4 mock")

        from src.llm.client import structured_complete as real_sc
        atj_module.structured_complete = real_sc  # type: ignore[assignment]

        result = await apply_to_job(
            job=job,
            profile=make_profile(),
            cover_letter=make_cover_letter(),
            tailored_resume_pdf=resume_pdf,
            dry_run=True,
            confirm=False,
            client=ActionbookClient(),
            history_path=td_p / "applications.json",
            screenshot_dir=td_p / "shots",
            max_steps=20,
        )

    print(f"  live result: method={result.method_used} steps={result.steps_taken}")
    print(f"  screenshot:  {result.screenshot_path}")
    _check("live run reached a terminal state",
           result.method_used in ("manual_review", "actionbook_form", "duplicate"))
    _check("nothing was actually submitted",
           result.success is False, "if True, real submit happened — investigate")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("apply_to_job tests (Actionbook v0.4.2 API)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        tests = [
            ("t1", test_dedup_short_circuit),
            ("t2", test_preflight_placeholder_profile),
            ("t3", test_preflight_missing_resume_pdf),
            ("t4", test_dry_run_intercepts_submit),
            ("t5", test_done_path_success),
            ("t6", test_stuck_on_captcha),
            ("t7", test_anti_loop_guard),
            ("t8", test_low_confidence_submit_blocked),
            ("t9", test_inconsistent_decision_rejected),
            ("t10", test_max_steps_exhaustion),
            ("t11", test_history_records_and_dedupes),
        ]
        for name, fn in tests:
            subdir = td_path / name
            subdir.mkdir(parents=True, exist_ok=True)
            await fn(subdir)

    if os.environ.get("LIVE") == "1":
        await test_live_dry_run()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
