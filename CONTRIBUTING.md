# Contributing to AgentField Apply Bot

Thanks for contributing! This guide explains how to set up your environment, make changes safely, and submit high-quality pull requests.

## Ground Rules

- Keep changes **schema-first** and **typed**.
- Prefer small, focused PRs.
- Preserve safety defaults (especially around real job submissions).
- Never commit secrets, personal profile data, or generated private artifacts.

## Development Setup

```bash
git clone https://github.com/jose2505207-eng/agentfield-apply-bot.git
cd agentfield-apply-bot

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create local config:

1. `.env` (gitignored)
   - `OPENAI_API_KEY=...`
   - `LLM_PROVIDER=openai`
   - `OPENAI_MODEL=gpt-4o-mini`
2. `data/profile.json` from `data/profile.template.json`

## Project Architecture (Contributor View)

Pipeline:

`search_jobs → score_match → tailor_resume + tailor_cover_letter → render_pdf → apply_to_job`

Key principles:

- **Reasoners** own business logic for each step.
- **Schemas (Pydantic v2)** are contracts between modules.
- **LLM access** goes through `structured_complete(...)` only.
- **Adapters** isolate external systems (job boards, browser automation).

## Coding Guidelines

### Python

- Follow PEP 8 and use clear, descriptive naming.
- Add type hints to public functions.
- Keep functions focused; avoid large mixed-responsibility blocks.
- Prefer explicit error handling with actionable messages.

### Schema Discipline

- Update schemas first when changing input/output shapes.
- Avoid passing unvalidated raw dicts across module boundaries.
- Keep backward compatibility in mind for persisted data.

### LLM Integration

- Do not call provider SDKs directly from reasoners.
- Route all model calls through `src/llm/client.py`.
- Keep prompts deterministic and tied to schema outputs.

### Safety for Application Automation

- Keep `dry_run=True` as default behavior in examples/tests unless explicitly testing real submissions.
- Do not weaken guardrails (loop detection, low-confidence destructive actions) without strong rationale and tests.

## Testing

Tests are module-driven (not pytest collection). Run from repo root with venv active:

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

### Live Tests

Only run live tests when you have the required local services and credentials configured:

```bash
LIVE=1 APPLY_TEST_URL='https://jobs.lever.co/<co>/<id>/apply' python -m tests.test_apply_to_job
SKIP_LIVE=0 python -m tests.test_actionbook_client
```

## Branching & Commits

- Create feature branches from the default branch.
- Use clear commit messages, e.g.:
  - `feat: add greenhouse adapter pagination`
  - `fix: prevent duplicate history writes on retry`
  - `docs: clarify apply_to_job dry-run behavior`

## Pull Request Checklist

Before opening a PR, ensure:

- [ ] Change is scoped and documented.
- [ ] Relevant tests pass locally.
- [ ] New behavior includes/updates tests.
- [ ] No secrets/PII are committed.
- [ ] README/docs updated if behavior changed.

In your PR description include:

- Problem statement
- Approach/implementation summary
- Test evidence (commands + results)
- Any follow-up work or known limitations

## Security & Privacy

- Never commit `.env`, API keys, session tokens, or personal job profile data.
- Treat `data/profile.json` and generated application artifacts as sensitive.
- If you find a security issue, report it privately to maintainers (do not open a public issue with exploit details).

## Where to Contribute

High-impact areas:

- New job adapters in `src/adapters/jobs/`
- Better action validation/recovery in `apply_to_job`
- Prompt + schema quality improvements for reasoners
- PDF template and rendering robustness
- Test coverage for edge cases and failures

---

Thanks again for helping improve AgentField Apply Bot.
