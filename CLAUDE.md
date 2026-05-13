# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Activate the venv before running anything
source venv/bin/activate

# Run all tests (custom runner, not pytest)
python -m tests.test_apply_to_job
python -m tests.test_actionbook_client
python -m tests.test_parse_resume
python -m tests.test_score_match
python -m tests.test_tailor_resume
python -m tests.test_tailor_cover_letter
python -m tests.test_render_pdf
python -m tests.test_search_jobs
python -m tests.test_resume_filters

# Live end-to-end test (requires Actionbook daemon + Chrome extension + OPENAI_API_KEY)
LIVE=1 APPLY_TEST_URL='https://jobs.lever.co/<co>/<id>/apply' python -m tests.test_apply_to_job

# Live Actionbook smoke test (requires browser + extension)
SKIP_LIVE=0 python -m tests.test_actionbook_client
```

Tests use a hand-rolled runner (PASS/FAIL counters, `sys.exit(1)` on failure) — not pytest. Each test file runs standalone via `python -m tests.<name>`.

WeasyPrint (PDF rendering) requires system libs. If you see Pango/cairo errors:
```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

## Environment

`.env` (gitignored) sets `OPENAI_API_KEY`, `LLM_PROVIDER` (default `openai`), and `OPENAI_MODEL` (default `gpt-4o-mini`).

`data/profile.json` (gitignored, PII): copy `data/profile.template.json` and fill in real values. Fields containing `FILL_ME` block `apply_to_job` from running.

`data/applications.json` (gitignored): append-only history of every application attempt written by `record_application()`.

## Architecture

This is an autonomous job-application pipeline. The full flow:

```
search_jobs → score_match → tailor_resume + tailor_cover_letter → render_pdf → apply_to_job
```

### Layer map

**`src/schemas/`** — Pydantic v2 models that are the contracts between every layer. Nothing is passed as raw dicts between reasoners; it always goes through a schema.

**`src/llm/client.py`** — Single entry point: `structured_complete(schema, system, user)`. Returns a parsed Pydantic instance. Reasoners never import `openai` directly. Provider is selected by `LLM_PROVIDER` env var; add new providers in `src/llm/providers/`.

**`src/reasoners/`** — One async function per pipeline step. Each takes schemas in, returns schemas out, and calls `structured_complete` once (except `search_jobs`, which makes zero LLM calls).

**`src/adapters/jobs/`** — Job source adapters (currently only `RemoteOKAdapter`). All implement `JobAdapter.search(query, max_results)` and return `list[JobPosting]`. Register new sources in `search_jobs.ADAPTERS`.

**`src/adapters/browser/actionbook_client.py`** — Async wrapper around the `actionbook` CLI binary (Rust, shelled out via `asyncio.create_subprocess_exec`). Every browser command requires **both** `--session` and `--tab`. Returns `BrowserSession(session_id, tab_id)` from `start_session()`. Snapshots are YAML files written to disk by the CLI; `snapshot()` parses the path from stdout and reads the file.

**`src/render/`** — Jinja2 + WeasyPrint. No LLM. `ParsedResume`, `TailoredResume`, and `CoverLetter` → PDF files on disk.

**`src/utils/application_history.py`** — Atomic append-only JSON log (`os.replace` for POSIX atomicity). Dedup key: `"{source}:{job_id}"`. Corrupt history is backed up and treated as empty rather than crashing.

**`src/utils/resume_filters.py`** — Pre-processing: strips skills with beginner markers (e.g. `"Docker (basics)"`) from resumes AND `ScoreResult` lists before passing to content-generation LLM calls, so the LLM can't amplify learning-level skills into core claims.

### The demo: `apply_to_job`

`src/reasoners/apply_to_job.py` is the main loop. Contract:

1. Three preflights: profile has no `FILL_ME`, job not already in history, resume PDF exists.
2. `start_session(open_url=job.url)` → `BrowserSession`.
3. Loop up to `max_steps=25`: snapshot → `structured_complete(ActionDecision)` → validate → execute.
4. Terminal exits: `done` (success), `stuck` (manual review), `submit` in dry-run (screenshot + hold), anti-loop guard (same `(kind, ref, value)` 3× in a row), low-confidence destructive action, LLM schema inconsistency, `ActionbookError`, max-steps exhaustion.
5. Every exit path calls `record_application(ApplyResult)`.

The `ActionDecision` schema uses a discriminated `kind` literal (`click|fill|select|upload|wait|scroll|submit|done|stuck`) to force the LLM to target actual refs from the snapshot rather than generating free-form selectors. Ref syntax: snapshots label elements `[ref=e5]`; commands target them as `@e5`.

`apply_to_job` defaults to `dry_run=True`. Pass `dry_run=False, confirm=True` for a real submission.
