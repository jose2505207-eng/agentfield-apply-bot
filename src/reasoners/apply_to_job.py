"""
apply_to_job reasoner — the autonomous apply loop. THIS IS THE DEMO.

ONE-LINE PITCH:
  "Snapshot the page → ask the LLM what to do next → execute → repeat."

WHY THIS DESIGN BEATS PER-SITE 'MANUALS':
  Pre-recorded Actionbook manuals can't cover Wellfound, Greenhouse, Lever,
  Workday, Ashby, custom company sites, and every variant they ship every
  month. A generic snapshot+LLM loop handles all of them because the LLM
  reads the actual page state and picks the actual next step.

LOOP CONTRACT (the spec the demo lives or dies by):
  while step < max_steps:
      snapshot  = await ab.snapshot(session)
      decision  = await structured_complete(ActionDecision, ...)
      history.append(decision)
      if decision.kind == 'done':   → record success, return
      if decision.kind == 'stuck':  → record manual_review (CAPTCHA / login wall / unknown), return
      if decision.kind == 'submit' and (dry_run or not confirm):
          → screenshot moment-of-truth, record manual_review with dry_run=True, return
      _execute(decision)   # click/fill/select/upload/wait/scroll/submit
  → timeout: record manual_review with steps_taken=max_steps

ANTI-LOOP GUARD:
  If the LLM emits the same (kind, ref) three times in a row, we bail to
  manual_review. The LLM is stuck in a fixed point even if it doesn't say so.

DEFENSIVE LAYERS:
  1. Profile preflight  — refuses to run if profile has FILL_ME placeholders.
  2. Dedup preflight    — short-circuits if we already applied to this job.
  3. Confidence gate    — low confidence on destructive action (upload, submit)
                          aborts the loop with a screenshot, not a click.
  4. Consistency check  — if kind='submit' but is_terminal=True, treat as
                          schema violation and abort (the LLM contradicted
                          itself; don't trust the action).
  5. Max steps          — hard cap (default 25) so we never run forever.

WHY THE LLM SEES PROFILE + JOB + COVER LETTER:
  - Profile so it can fill EEO/work-auth fields without inventing answers.
  - Job (title, company, url) so it can answer "what role are you applying to?"
  - Cover letter text so it can paste it into a "Cover letter" textarea
    instead of generating new prose mid-application.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from src.llm.client import structured_complete
from src.schemas.action_decision import ActionDecision
from src.schemas.apply_result import ApplyResult
from src.schemas.candidate_profile import CandidateProfile
from src.schemas.cover_letter import CoverLetter
from src.schemas.job import JobPosting
from src.adapters.browser.actionbook_client import (
    ActionbookClient,
    ActionbookError,
)
from src.utils.application_history import (
    already_applied,
    record_application,
    DEFAULT_HISTORY_PATH,
)


# How many of the last decisions we feed back to the LLM as "what you've
# already tried". Keeps prompt size bounded — older history is dropped.
_HISTORY_WINDOW = 8

# Anti-loop guard: same (kind, ref) emitted this many times in a row → bail.
_REPEAT_LIMIT = 3

# Default scroll delta in pixels when LLM asks to scroll. Empirical: large
# enough to reveal new fields below the fold, small enough to not skip them.
_SCROLL_DELTA_PX = 800

# Cap how long a single "wait" action can pause. The LLM sometimes asks for
# absurd values (e.g. value='30') — we clamp.
_MAX_WAIT_SECONDS = 5.0


SYSTEM_PROMPT = """You are an autonomous job-application agent operating a real Chrome browser.

You receive on every step:
  - A text "snapshot" of the current page: each interactive element has a
    short label and a ref like `@e5` you can target.
  - The candidate's personal profile (name, email, work auth, demographics).
  - The job posting being applied to.
  - The cover letter text the candidate wants to submit.
  - History of the actions you have already taken in this session.

You output ONE ActionDecision per call. Your action is then executed against
the real browser, and you are called again with a fresh snapshot.

# AVAILABLE ACTIONS (the `kind` field)

- click   — click a button, link, or radio. `ref` required.
- fill    — type into a text input or textarea. `ref` required, `value` required.
- select  — choose an option in a <select>. `ref` required, `value` required
            (use the visible label of the option you want).
- upload  — attach a file to a file input. `ref` required, `value` = absolute
            path to the file (you will be told which path to use for resume/CL).
- wait    — pause N seconds for the page to settle. `value` = seconds as string
            (e.g. "2"). Use after navigations or dynamic loads, NOT as a stall.
- scroll  — scroll the page down to reveal more content in the next snapshot.
            Use when you suspect there are required fields below the fold.
- submit  — click the final submit button. THIS IS THE MOMENT OF TRUTH.
- done    — emit ONLY when the snapshot clearly shows a confirmation page
            ("Application submitted", "Thank you for applying", etc.).
- stuck   — emit when you cannot proceed: CAPTCHA, login wall, an unknown
            required field with no value in the profile, or any genuine
            ambiguity. `reasoning` MUST explain why.

# HARD RULES

R1. NEVER invent answers. Every value you fill comes from the profile, the
    job posting, the cover letter, or is a direct copy of text already on
    the page (e.g. "Yes" for a yes/no question whose answer the profile
    makes obvious).

R2. Work-auth and EEO questions: use ONLY the profile's literal values.
    If the form asks a question whose answer is not in the profile, emit
    `stuck` with reasoning naming the field.

R3. File uploads: use ONLY the absolute paths you are told in the user
    message under "Files available to upload". Never make up a path.

R4. Cover-letter textareas: when a textarea asks for a cover letter or a
    "Why are you interested?" / "Tell us about yourself" prose answer,
    paste the cover-letter text from the user message. Do not regenerate.

R5. Before `submit`, verify visually (via the snapshot) that all required
    fields appear filled. If you see a required field still empty, do NOT
    emit submit — fill that field first.

R6. Confidence calibration:
      - high   = you are sure this is the right action right now.
      - medium = the action is correct but you have minor doubt (e.g. two
                 similar-looking dropdown options).
      - low    = you would not bet on this. Reserve for destructive actions
                 where you are guessing. The system aborts to manual review
                 on low-confidence destructive actions.

R7. `is_terminal` MUST be True for `done` and `stuck`, and False for every
    other kind (including `submit`).

R8. If the same action did not change the page in the previous step, do NOT
    repeat it. Try something else (scroll, wait, or stuck).

R9. NEVER reuse a credit-card / SSN / password field — the profile contains
    none of these. If the form demands them, emit `stuck`.

# DRY-RUN MODE

When the user message states "DRY-RUN MODE: ON", you may proceed all the way
to emitting `submit` — the system will intercept that decision, screenshot
the page, and return without actually clicking the button. Your job is to
get the form into a ready-to-submit state, not to skip submit.
"""


# ----------------------------------------------------------------------
# Prompt formatting helpers
# ----------------------------------------------------------------------


def _format_profile(profile: CandidateProfile) -> str:
    return (
        "# Candidate profile (use these EXACTLY, do not invent)\n"
        f"- Full name: {profile.full_name}\n"
        f"- Email: {profile.email}\n"
        f"- Phone: {profile.phone}\n"
        f"- Location: {profile.location_city}, {profile.location_state}, "
        f"{profile.location_country}\n"
        f"- LinkedIn: {profile.linkedin_url or '(not set — leave blank)'}\n"
        f"- GitHub: {profile.github_url or '(not set — leave blank)'}\n"
        f"- Portfolio: {profile.portfolio_url or '(not set — leave blank)'}\n"
        f"- Work auth: {profile.work_auth_status}\n"
        f"- Needs visa sponsorship (now or in future): "
        f"{'Yes' if profile.requires_visa_sponsorship_now_or_future else 'No'}\n"
        f"- Gender: {profile.gender}\n"
        f"- Ethnicity: {profile.ethnicity}\n"
        f"- Veteran status: {profile.veteran_status}\n"
        f"- Disability status: {profile.disability_status}\n"
        f"- Salary expectation USD: "
        f"{profile.salary_expectation_usd if profile.salary_expectation_usd else 'Negotiable'}\n"
        f"- Earliest start date: "
        f"{profile.earliest_start_date or 'Immediately / two weeks notice'}\n"
        f"- Willing to relocate: "
        f"{'Yes' if profile.willing_to_relocate else 'No'}\n"
        f"- How did you hear: {profile.how_did_you_hear or '(use job source)'}\n"
        f"- Pronouns: {profile.pronouns or '(leave blank)'}"
    )


def _format_job(job: JobPosting) -> str:
    return (
        "# Job being applied to\n"
        f"- Title: {job.title}\n"
        f"- Company: {job.company}\n"
        f"- Source: {job.source}\n"
        f"- URL: {job.url}\n"
        f"- Location: {job.location or 'not stated'}"
        f"{' (remote)' if job.is_remote else ''}"
    )


def _format_cover_letter(cl: CoverLetter) -> str:
    body = "\n\n".join(cl.body_paragraphs)
    return (
        "# Cover letter to paste into 'Cover letter' textareas (verbatim)\n\n"
        f"{cl.greeting}\n\n{body}\n\n{cl.sign_off}"
    )


def _format_history(history: list[ActionDecision]) -> str:
    if not history:
        return "# History\n(none — this is the first step)"
    lines = ["# History (most recent last) — actions you've ALREADY taken:"]
    for i, d in enumerate(history[-_HISTORY_WINDOW:], start=1):
        val_part = f" value={d.value!r}" if d.value else ""
        ref_part = f" ref={d.ref}" if d.ref else ""
        lines.append(
            f"  {i}. kind={d.kind}{ref_part}{val_part} "
            f"(confidence={d.confidence}) — {d.reasoning}"
        )
    return "\n".join(lines)


def _format_files(resume_pdf: Path, cover_letter_pdf: Optional[Path]) -> str:
    lines = ["# Files available to upload (use these absolute paths verbatim)"]
    lines.append(f"- Resume (PDF): {resume_pdf.resolve()}")
    if cover_letter_pdf:
        lines.append(f"- Cover letter (PDF): {cover_letter_pdf.resolve()}")
    return "\n".join(lines)


def _build_user_prompt(
    *,
    snapshot: str,
    profile: CandidateProfile,
    job: JobPosting,
    cover_letter: CoverLetter,
    resume_pdf: Path,
    cover_letter_pdf: Optional[Path],
    history: list[ActionDecision],
    dry_run: bool,
    step: int,
    max_steps: int,
) -> str:
    dry_line = "DRY-RUN MODE: ON" if dry_run else "DRY-RUN MODE: OFF (real submission)"
    return (
        f"{dry_line}\n"
        f"Step {step + 1} of {max_steps} max.\n\n"
        f"{_format_profile(profile)}\n\n"
        f"{_format_job(job)}\n\n"
        f"{_format_cover_letter(cover_letter)}\n\n"
        f"{_format_files(resume_pdf, cover_letter_pdf)}\n\n"
        f"{_format_history(history)}\n\n"
        "# Current page snapshot (your eye into the browser)\n"
        f"{snapshot}\n\n"
        "Decide the ONE next action. Return an ActionDecision."
    )


# ----------------------------------------------------------------------
# Validation of the LLM's decision before we execute it
# ----------------------------------------------------------------------


def _validate_decision(d: ActionDecision) -> Optional[str]:
    """Return an error string if the decision violates schema-consistency rules.

    Pydantic enforces types and the Literal kinds; this enforces semantic
    rules that span fields (e.g. ref required for click).
    """
    # is_terminal consistency
    if d.kind in ("done", "stuck") and not d.is_terminal:
        return f"kind={d.kind} requires is_terminal=True, got False"
    if d.kind not in ("done", "stuck") and d.is_terminal:
        return f"kind={d.kind} requires is_terminal=False, got True"

    # ref requirement
    if d.kind in ("click", "fill", "select", "upload") and not d.ref:
        return f"kind={d.kind} requires a ref but got None"

    # value requirement
    if d.kind in ("fill", "select", "upload") and not d.value:
        return f"kind={d.kind} requires a value but got None/empty"

    if d.kind == "wait":
        if not d.value:
            return "kind=wait requires a value (seconds as string)"
        try:
            float(d.value)
        except ValueError:
            return f"kind=wait value must be numeric, got {d.value!r}"

    return None


def _is_repeating(history: list[ActionDecision]) -> bool:
    """True if the last _REPEAT_LIMIT decisions had identical (kind, ref, value)."""
    if len(history) < _REPEAT_LIMIT:
        return False
    last = history[-_REPEAT_LIMIT:]
    fingerprint = (last[0].kind, last[0].ref, last[0].value)
    return all((d.kind, d.ref, d.value) == fingerprint for d in last)


# ----------------------------------------------------------------------
# Action dispatcher — kind → ActionbookClient method
# ----------------------------------------------------------------------


async def _execute(
    decision: ActionDecision,
    *,
    client: ActionbookClient,
    session: str,
) -> None:
    """Translate an ActionDecision into one or more ActionbookClient calls.

    Caller is responsible for handling the terminal kinds (done, stuck, submit).
    This function is only called for executable, non-terminal actions.
    """
    kind = decision.kind

    if kind == "click":
        await client.click(decision.ref, session=session)  # type: ignore[arg-type]

    elif kind == "fill":
        await client.fill(decision.ref, decision.value, session=session)  # type: ignore[arg-type]

    elif kind == "select":
        await client.select(decision.ref, decision.value, session=session)  # type: ignore[arg-type]

    elif kind == "upload":
        await client.upload(decision.ref, decision.value, session=session)  # type: ignore[arg-type]

    elif kind == "wait":
        seconds = max(0.0, min(_MAX_WAIT_SECONDS, float(decision.value or "1")))
        await client.wait(seconds)

    elif kind == "scroll":
        # The wrapper does not expose a `scroll` command directly; emulate
        # with JS. Documented in actionbook_client.py.
        await client.eval_js(
            f"window.scrollBy(0, {_SCROLL_DELTA_PX})",
            session=session,
        )

    elif kind == "submit":
        # The caller decides whether we ever get here. In real-submit mode,
        # this is the one and only time we click submit.
        # If the LLM provided a ref, use it; otherwise the LLM should have
        # pointed at the submit button via `ref`. We require it for safety.
        if not decision.ref:
            raise ActionbookError(
                cmd="submit",
                returncode=-1,
                stderr="kind=submit requires ref pointing to the submit button",
            )
        await client.click(decision.ref, session=session)

    else:
        # done/stuck handled before dispatch; this branch means a bug.
        raise ValueError(f"_execute called with non-executable kind={kind}")


# ----------------------------------------------------------------------
# Result builders — every exit path goes through one of these
# ----------------------------------------------------------------------


def _base_result(
    *,
    job: JobPosting,
    session_id: Optional[str],
    cover_letter_pdf: Optional[Path],
    resume_pdf: Optional[Path],
) -> dict:
    return dict(
        job_id=job.id,
        job_source=job.source,
        job_title=job.title,
        company=job.company,
        apply_url=job.url,
        actionbook_session_id=session_id,
        cover_letter_path=str(cover_letter_pdf) if cover_letter_pdf else None,
        resume_path=str(resume_pdf) if resume_pdf else None,
    )


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------


async def apply_to_job(
    job: JobPosting,
    profile: CandidateProfile,
    cover_letter: CoverLetter,
    tailored_resume_pdf: Path,
    *,
    cover_letter_pdf: Optional[Path] = None,
    dry_run: bool = True,
    confirm: bool = False,
    max_steps: int = 25,
    client: Optional[ActionbookClient] = None,
    history_path: Path = DEFAULT_HISTORY_PATH,
    screenshot_dir: Path = Path("output/apply_screenshots"),
) -> ApplyResult:
    """Run the autonomous apply loop for a single job.

    Args:
        job: The job to apply to. Must have a working `url`.
        profile: The candidate's personal data.
        cover_letter: The tailored cover letter (text, used for textareas).
        tailored_resume_pdf: Path to the resume PDF to upload.
        cover_letter_pdf: Optional path to the cover-letter PDF, if some
            sites prefer file uploads over textareas.
        dry_run: If True, the loop never actually clicks the final submit;
            it screenshots the moment-of-truth and exits as manual_review.
        confirm: If False, ANY emission of `submit` is treated as dry-run
            even if dry_run=False. The user must explicitly pass confirm=True
            to allow real submissions.
        max_steps: Hard cap on loop iterations.
        client: Inject a custom ActionbookClient for tests. Production passes None.
        history_path: Where to read/write the applications log.
        screenshot_dir: Where to save the moment-of-truth and stuck screenshots.

    Returns:
        ApplyResult — never raises for normal failure modes. Network/Chrome
        crashes propagate as preflight_failed / stuck.
    """
    base = _base_result(
        job=job,
        session_id=None,
        cover_letter_pdf=cover_letter_pdf,
        resume_pdf=tailored_resume_pdf,
    )

    # ---- Preflight 1: profile has no FILL_ME placeholders ----
    unfilled = profile.has_unfilled_placeholders()
    if unfilled:
        result = ApplyResult(
            **base,
            success=False,
            method_used="preflight_failed",
            dry_run=dry_run,
            error_message=(
                f"profile.json still has placeholder values in: "
                f"{', '.join(unfilled)}. Fill these before applying."
            ),
        )
        record_application(result, history_path=history_path)
        return result

    # ---- Preflight 2: dedup ----
    prev = already_applied(job, history_path=history_path)
    if prev is not None:
        result = ApplyResult(
            **base,
            success=True,  # we count duplicate-of-success as success
            method_used="duplicate",
            dry_run=dry_run,
            error_message=None,
            last_action_reasoning=(
                f"already applied on {prev.get('sent_at', 'unknown')} "
                f"via {prev.get('method_used', 'unknown')}"
            ),
        )
        record_application(result, history_path=history_path)
        return result

    # ---- Preflight 3: resume file actually exists ----
    if not Path(tailored_resume_pdf).is_file():
        result = ApplyResult(
            **base,
            success=False,
            method_used="preflight_failed",
            dry_run=dry_run,
            error_message=f"resume PDF not found at {tailored_resume_pdf}",
        )
        record_application(result, history_path=history_path)
        return result

    # ---- Browser session ----
    ab = client or ActionbookClient()
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    try:
        session = await ab.start_session()
    except ActionbookError as e:
        result = ApplyResult(
            **base,
            success=False,
            method_used="preflight_failed",
            dry_run=dry_run,
            error_message=f"could not start Actionbook session: {e}",
        )
        record_application(result, history_path=history_path)
        return result

    base["actionbook_session_id"] = session

    try:
        await ab.open(job.url, session=session)
        # Give the page a moment to settle before the first snapshot.
        await ab.wait(2.0)
    except ActionbookError as e:
        result = ApplyResult(
            **base,
            success=False,
            method_used="preflight_failed",
            dry_run=dry_run,
            error_message=f"could not open apply URL: {e}",
        )
        record_application(result, history_path=history_path)
        return result

    history: list[ActionDecision] = []
    last_decision: Optional[ActionDecision] = None

    for step in range(max_steps):
        # 1. Snapshot
        try:
            snapshot = await ab.snapshot(session=session)
        except ActionbookError as e:
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step,
                error_message=f"snapshot failed at step {step}: {e}",
                last_action_reasoning=(
                    last_decision.reasoning if last_decision else None
                ),
            )
            record_application(result, history_path=history_path)
            return result

        # 2. LLM decides
        user_prompt = _build_user_prompt(
            snapshot=snapshot,
            profile=profile,
            job=job,
            cover_letter=cover_letter,
            resume_pdf=tailored_resume_pdf,
            cover_letter_pdf=cover_letter_pdf,
            history=history,
            dry_run=dry_run,
            step=step,
            max_steps=max_steps,
        )

        decision = await structured_complete(
            schema=ActionDecision,
            system=SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
        )

        # 3. Validate consistency
        problem = _validate_decision(decision)
        if problem:
            # Don't trust an inconsistent decision. Bail to manual review.
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "inconsistent"
            )
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=f"LLM produced inconsistent decision: {problem}",
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        history.append(decision)
        last_decision = decision

        # 4. Anti-loop check
        if _is_repeating(history):
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "repeating"
            )
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=(
                    f"LLM stuck in a loop: repeated kind={decision.kind} "
                    f"ref={decision.ref} value={decision.value!r} "
                    f"{_REPEAT_LIMIT} times"
                ),
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        # 5. Terminal kinds
        if decision.kind == "done":
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "done"
            )
            result = ApplyResult(
                **base,
                success=True,
                method_used="actionbook_form",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=None,
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        if decision.kind == "stuck":
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "stuck"
            )
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=decision.reasoning,
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        # 6. Submit intercept — dry-run or non-confirmed
        if decision.kind == "submit" and (dry_run or not confirm):
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "moment_of_truth"
            )
            result = ApplyResult(
                **base,
                success=False,  # nothing was submitted
                method_used="manual_review",
                dry_run=True,  # force True regardless of input flag
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=(
                    "DRY-RUN: LLM reached submit but execution was held back. "
                    "Inspect the screenshot and re-run with dry_run=False, "
                    "confirm=True to actually send."
                ),
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        # 7. Confidence gate on destructive kinds
        if decision.kind in ("submit", "upload") and decision.confidence == "low":
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "low_confidence_destructive"
            )
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=(
                    f"low-confidence {decision.kind} blocked; "
                    f"reasoning: {decision.reasoning}"
                ),
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

        # 8. Execute the non-terminal action
        try:
            await _execute(decision, client=ab, session=session)
        except ActionbookError as e:
            # Browser command failed (ref vanished, network blip, etc.).
            # Don't crash — return manual_review so the user can inspect.
            shot = await _safe_screenshot(
                ab, session, screenshot_dir, job, "exec_failed"
            )
            result = ApplyResult(
                **base,
                success=False,
                method_used="manual_review",
                dry_run=dry_run,
                steps_taken=step + 1,
                screenshot_path=shot,
                final_url=await _safe_current_url(ab, session),
                error_message=f"executing {decision.kind} failed: {e}",
                last_action_reasoning=decision.reasoning,
            )
            record_application(result, history_path=history_path)
            return result

    # ---- Exhausted max_steps without terminating ----
    shot = await _safe_screenshot(
        ab, session, screenshot_dir, job, "timeout"
    )
    result = ApplyResult(
        **base,
        success=False,
        method_used="manual_review",
        dry_run=dry_run,
        steps_taken=max_steps,
        screenshot_path=shot,
        final_url=await _safe_current_url(ab, session),
        error_message=f"exceeded max_steps={max_steps} without terminating",
        last_action_reasoning=last_decision.reasoning if last_decision else None,
    )
    record_application(result, history_path=history_path)
    return result


# ----------------------------------------------------------------------
# Defensive helpers — never let diagnostic actions crash the result
# ----------------------------------------------------------------------


async def _safe_screenshot(
    ab: ActionbookClient,
    session: str,
    out_dir: Path,
    job: JobPosting,
    tag: str,
) -> Optional[str]:
    """Try to save a screenshot; return None on failure rather than raising."""
    import time as _t
    fname = (
        f"{int(_t.time())}__{job.source}__{job.id}__{tag}.png".replace(
            "/", "_"
        )
    )
    path = out_dir / fname
    try:
        return await ab.screenshot(str(path), session=session)
    except ActionbookError:
        return None


async def _safe_current_url(
    ab: ActionbookClient,
    session: str,
) -> Optional[str]:
    """Best-effort current URL; None if the eval fails."""
    try:
        return await ab.current_url(session=session)
    except ActionbookError:
        return None
