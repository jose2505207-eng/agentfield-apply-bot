"""
application_history — append-only log of every apply_to_job attempt.

WHY A FLAT JSON FILE INSTEAD OF SQLITE / POSTGRES:
  This is one append-per-application on a single user's laptop. SQLite would
  be defensible but adds a migration burden for a hackathon timeline. A flat
  JSON list, atomically replaced on every write, is enough — and the same
  file shows beautifully in the demo UI ("look, here's everything the bot
  ever did").

WHY ATOMIC WRITES MATTER HERE:
  apply_to_job runs for up to a couple minutes per job. If the user kills
  the process mid-write, a naive open('w') would leave a half-written file
  and corrupt the history. We always write to <path>.tmp first and then
  os.replace to the final path — which is atomic on POSIX.

DEDUP KEY:
  '{source}:{id}' — the same string ApplyResult.dedup_key returns. Picked
  this format so a human reading data/applications.json can tell at a glance
  which source claimed each application.

ROBUSTNESS:
  - history file missing  → treat as empty list, do NOT raise
  - history file corrupt  → back up to applications.corrupt.<ts>.json, then
                            treat as empty list. Better than crashing the
                            apply pipeline because a stray editor mangled
                            the JSON.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from src.schemas.apply_result import ApplyResult
from src.schemas.job import JobPosting


# Default location. apply_to_job and tests can pass an override.
DEFAULT_HISTORY_PATH = Path("data/applications.json")


def _dedup_key_for_job(job: JobPosting) -> str:
    """Canonical dedup key for a job — must match ApplyResult.dedup_key format."""
    return f"{job.source}:{job.id}"


def _load_history(path: Path) -> list[dict]:
    """Read raw history as a list of dicts. Empty list if missing or corrupt.

    We return dicts (not ApplyResult instances) because the schema might evolve
    and we don't want loading old history to fail validation. The caller decides
    which fields matter (dedup just looks at dedup_key).
    """
    if not path.exists():
        return []

    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("history file is not a JSON list")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        # Back up the corrupt file so we don't silently lose data.
        backup = path.with_name(f"{path.stem}.corrupt.{int(time.time())}.json")
        try:
            path.rename(backup)
        except OSError:
            pass  # if we can't rename it, at least we're not crashing
        print(
            f"[application_history] WARNING: corrupt history at {path} "
            f"({e}). Backed up to {backup}. Starting fresh."
        )
        return []


def already_applied(
    job: JobPosting,
    history_path: Path = DEFAULT_HISTORY_PATH,
) -> Optional[dict]:
    """Return the previous successful application entry if we already applied to this job.

    Returns:
        The previous ApplyResult-dict (raw) if found AND success=True OR
        method_used in ('actionbook_form', 'duplicate'). None otherwise.

    DESIGN NOTE: a 'manual_review' from a previous dry-run does NOT count as
    "already applied" — the user may want to retry it with confirm=True. Only
    a real submission or a previously-recorded duplicate blocks re-apply.
    """
    key = _dedup_key_for_job(job)
    history = _load_history(history_path)

    for entry in history:
        entry_key = f"{entry.get('job_source', '')}:{entry.get('job_id', '')}"
        if entry_key != key:
            continue
        # Only count as "applied" if it was an actual submission.
        if entry.get("success") is True:
            return entry
        if entry.get("method_used") == "actionbook_form":
            return entry
    return None


def record_application(
    result: ApplyResult,
    history_path: Path = DEFAULT_HISTORY_PATH,
) -> None:
    """Append `result` to the history file. Atomic — never leaves a half-written file.

    Process:
      1. Load current history (empty list if missing/corrupt)
      2. Append the new entry as a dict (Pydantic .model_dump with JSON-safe types)
      3. Write entire new list to <path>.tmp
      4. os.replace(<path>.tmp, <path>)  — atomic on POSIX, near-atomic on Windows
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)

    history = _load_history(history_path)
    history.append(result.model_dump(mode="json"))

    tmp_path = history_path.with_suffix(history_path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp_path, history_path)
