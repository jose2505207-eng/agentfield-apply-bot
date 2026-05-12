"""
ApplyResult schema.

Output of apply_to_job. The audit / log record of one attempted application.
Persisted to data/applications.json (one entry per attempt) for:
  - Dedup: don't apply twice to the same job (job_source + job_id is the key)
  - Demo: show the judges the history of what the bot did
  - Debug: trace which jobs got stuck and why

WHY KEEP REDUNDANT FIELDS (job_title, company):
  Reading data/applications.json with only IDs is debugging hell.
  Redundancy with job_id costs ~50 bytes per entry; readability is worth it.
  Same principle as `original` and `rewritten` in BulletChange.

WHY screenshot_path EVEN FOR dry_run:
  When dry_run=True or confirm=False, the bot navigates the full form and
  screenshots the moment-of-truth (final review page) BEFORE clicking submit.
  That screenshot is what the user inspects in the UI before approving the
  real submit. For real submits, the screenshot is the post-submit
  confirmation page.

WHY method_used='duplicate' IS A KIND:
  Calling apply_to_job() on a job already applied to should NOT raise — it
  should return a clean result indicating duplicate so the pipeline keeps
  going. Errors are reserved for actual failures.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, Literal
from pydantic import BaseModel, Field


ApplyMethod = Literal[
    "actionbook_form",    # filled and submitted via the Actionbook + LLM loop
    "manual_review",      # bot navigated but did NOT submit (captcha, low-conf, dry_run)
    "duplicate",          # already applied previously; no work was done this run
    "preflight_failed",   # profile invalid, page unreachable, etc. — never got to the loop
]


class ApplyResult(BaseModel):
    """Record of one apply_to_job execution. Append-only to data/applications.json."""

    # ---- Identity of the attempted application ----
    job_id: str
    job_source: str = Field(description="'remoteok', 'wellfound', etc.")
    job_title: str = Field(description="Redundant with job_id, but essential for human-readable logs")
    company: str
    apply_url: str

    # ---- Outcome ----
    success: bool = Field(
        description="True only when the form was actually submitted (or duplicate "
                    "of a previously successful submission). False for stuck, dry-run, "
                    "or any failure mode."
    )
    method_used: ApplyMethod
    dry_run: bool = Field(
        description="True if we navigated the form but did not click the final submit."
    )
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ---- Trace ----
    actionbook_session_id: Optional[str] = Field(
        default=None,
        description="The Actionbook browser session that ran this. "
                    "Null for duplicate or preflight_failed.",
    )
    steps_taken: int = Field(
        default=0,
        description="How many ActionDecision steps the LLM executed. "
                    "0 if duplicate or preflight_failed.",
    )
    screenshot_path: Optional[str] = Field(
        default=None,
        description="Absolute path to PNG of final state: "
                    "moment-of-truth for dry-run, confirmation page for real submit, "
                    "or the stuck-screen for manual_review.",
    )
    final_url: Optional[str] = Field(
        default=None,
        description="URL the browser landed on (often a 'thank you' page).",
    )

    # ---- Artifacts attached ----
    cover_letter_path: Optional[str] = Field(
        default=None, description="Cover letter PDF that was attached (if any).",
    )
    resume_path: Optional[str] = Field(
        default=None, description="Tailored resume PDF that was attached (if any).",
    )

    # ---- Failure diagnostics ----
    error_message: Optional[str] = Field(
        default=None,
        description="Why success=False, or the 'stuck' reason from the LLM. "
                    "Null if success=True.",
    )
    last_action_reasoning: Optional[str] = Field(
        default=None,
        description="The `reasoning` field of the LAST ActionDecision the LLM made. "
                    "Helps debug stuck/timeout cases by showing what the LLM was "
                    "thinking when it gave up.",
    )

    # ---- Dedup helpers ----
    @property
    def dedup_key(self) -> str:
        """Canonical key for dedup: '{source}:{id}'."""
        return f"{self.job_source}:{self.job_id}"
