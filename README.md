# AgentField Apply Bot

**AI-assisted job application workflow for modern job seekers.**

AgentField helps candidates discover relevant roles, tailor application materials, and complete applications faster—while keeping humans in control of final submissions.

## Why this project matters (for recruiters)

Recruiters and hiring teams often receive generic, untargeted applications. AgentField is designed to improve application quality by:

- **Matching candidates to better-fit roles** before applying.
- **Tailoring resumes and cover letters** to job requirements.
- **Standardizing application quality** with structured AI outputs.
- **Reducing friction** in repetitive application steps.

### Human-in-the-loop by default

This project is built with safety controls so candidates can review outputs before submission. By default, application mode is conservative (`dry_run=True`), and real submissions require explicit confirmation.

---

## Technical Overview

Autonomous, schema-driven job application pipeline:

**`search_jobs → score_match → tailor_resume + tailor_cover_letter → render_pdf → apply_to_job`**

### Features

- **End-to-end pipeline** from job discovery to application submission.
- **Strict schema contracts** (Pydantic v2) between all layers.
- **Single LLM entrypoint** (`structured_complete`) with pluggable providers.
- **Adapter-based job ingestion** (currently RemoteOK, extensible).
- **Browser automation via Actionbook CLI** with snapshot-guided actions.
- **Safe-by-default application mode** (`dry_run=True`).
- **Atomic append-only application history** with dedup + corruption recovery.
- **Resume skill filtering** to avoid inflating beginner-level skills.
- **PDF rendering** via Jinja2 + WeasyPrint.

### Repository Structure

```text
src/
  adapters/
    browser/
      actionbook_client.py      # Async wrapper around actionbook CLI
    jobs/
      ...                       # Job source adapters (RemoteOK, etc.)
  llm/
    client.py                   # structured_complete(schema, system, user)
    providers/                  # Provider implementations
  reasoners/                    # One async reasoner per pipeline step
    apply_to_job.py             # Main autonomous apply loop
  render/                       # Jinja2 + WeasyPrint PDF generation
  schemas/                      # Pydantic v2 contracts
  utils/
    application_history.py      # Atomic append-only history log
    resume_filters.py           # Beginner-skill filtering
tests/
  test_*.py                     # Standalone test modules (custom runner)
data/
  profile.template.json
```

### Requirements

- Python 3.10+ (recommended)
- Virtual environment (`venv`)
- Actionbook daemon + Chrome extension (for browser automation tests/live runs)
- `OPENAI_API_KEY` (or compatible provider credentials)
- System libraries for WeasyPrint (Pango/Cairo stack)

Install system libs if PDF rendering fails:

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

### Setup

```bash
git clone https://github.com/jose2505207-eng/agentfield-apply-bot.git
cd agentfield-apply-bot

python -m venv venv
source venv/bin/activate

# install deps (choose your project’s preferred method)
pip install -r requirements.txt
```

Create environment/config files:

1. Create `.env` (gitignored), e.g.
   - `OPENAI_API_KEY=...`
   - `LLM_PROVIDER=openai` (default)
   - `OPENAI_MODEL=gpt-4o-mini` (default)
2. Create `data/profile.json` by copying `data/profile.template.json`.
   - Fill all `FILL_ME` fields (required for `apply_to_job` preflight).

### How It Works

#### Pipeline

1. **`search_jobs`**  
   Uses registered adapters to fetch job postings (no LLM call).

2. **`score_match`**  
   Scores candidate-job fit using structured schema output.

3. **`tailor_resume`** + **`tailor_cover_letter`**  
   Generates targeted materials via LLM with strict schema parsing.

4. **`render_pdf`**  
   Converts tailored outputs into PDF assets (resume/cover letter).

5. **`apply_to_job`**  
   Runs browser automation loop with Actionbook snapshots + validated actions.

#### LLM Architecture

- All reasoners route through:
  - `src/llm/client.py` → `structured_complete(schema, system, user)`
- Reasoners do **not** import provider SDKs directly.
- Add providers under `src/llm/providers/`.

#### Safety Controls in `apply_to_job`

`apply_to_job` includes guardrails and deterministic exit paths:

- Preflight checks:
  - profile completeness (no `FILL_ME`)
  - no duplicate application in history
  - resume PDF exists
- Action loop (`max_steps=25`):
  - snapshot page
  - ask LLM for `ActionDecision`
  - validate + execute typed action
- Typed action kinds:
  - `click | fill | select | upload | wait | scroll | submit | done | stuck`
- Additional guards:
  - anti-loop detection (same action 3×)
  - low-confidence destructive action block
  - schema inconsistency handling
  - Actionbook error handling
- **Every exit path** records an `ApplyResult`.

By default:
- `dry_run=True` (safe mode)
- Real submission requires `dry_run=False, confirm=True`

### Testing

> Tests are **not pytest-based**.  
> Each test module is run directly via `python -m tests.<name>` and uses PASS/FAIL counters with `sys.exit(1)` on failure.

Activate venv first:

```bash
source venv/bin/activate
```

Run test modules:

```bash
python -m tests.test_apply_to_job
python -m tests.test_actionbook_client
python -m tests.test_parse_resume
python -m tests.test_score_match
python -m tests.test_tailor_resume
python -m tests.test_tailor_cover_letter
python -m tests.test_render_pdf
python -m tests.test_search_jobs
python -m tests.test_resume_filters
```

Live end-to-end test (requires Actionbook daemon + extension + API key):

```bash
LIVE=1 APPLY_TEST_URL='https://jobs.lever.co/<co>/<id>/apply' python -m tests.test_apply_to_job
```

Live Actionbook smoke test:

```bash
SKIP_LIVE=0 python -m tests.test_actionbook_client
```

### Data & Logging

- `data/profile.json` (gitignored): user profile / PII.
- `data/applications.json` (gitignored): append-only application history.
- Dedup key: `"{source}:{job_id}"`.
- Corrupt history handling: backup + treat as empty (non-fatal).

### Extending the Project

#### Add a new job source

1. Implement adapter in `src/adapters/jobs/` with:
   - `search(query, max_results) -> list[JobPosting]`
2. Register adapter in `search_jobs.ADAPTERS`.

#### Add a new LLM provider

1. Implement provider in `src/llm/providers/`.
2. Route selection via `LLM_PROVIDER`.
3. Keep reasoner interface unchanged (`structured_complete` only).

#### Add a new reasoner step

1. Define/extend schema contracts in `src/schemas/`.
2. Add one async reasoner function in `src/reasoners/`.
3. Keep I/O schema-validated (avoid raw dict crossing boundaries).

### Operational Notes

- Browser commands in Actionbook require both `--session` and `--tab`.
- Snapshot files are YAML written by Actionbook CLI and parsed by the client.
- For production-like runs, review anti-loop and confidence thresholds in `apply_to_job` before enabling non-dry submissions at scale.

### Disclaimer

Use responsibly and comply with each job platform’s terms of service.  
Always review generated materials and automated actions before real submission.

### License

Add your license here (e.g., MIT) if not already present in the repository.
