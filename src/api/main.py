"""
FastAPI backend — serves API endpoints AND the static Next.js frontend.

Option C architecture: one process, one port.
  - /api/*   → Python handlers
  - /*       → Next.js static files (frontend/out/ after `npm run build`)

Run locally:
  uvicorn src.api.main:app --reload --port 8000

Deploy (Zeabur / Railway / Render):
  uvicorn src.api.main:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.schemas.candidate_profile import CandidateProfile
from src.schemas.job import JobPosting
from src.reasoners.search_jobs import search_jobs


def _find_actionbook() -> str | None:
    """Return the actionbook binary path, searching PATH and common NVM locations."""
    import shutil, glob
    if path := shutil.which("actionbook"):
        return path
    # NVM installs node binaries under ~/.nvm/versions/node/*/bin/
    candidates = sorted(
        glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/actionbook")),
        reverse=True,  # newest version first
    )
    for c in candidates:
        if Path(c).is_file():
            return c
    return None

load_dotenv()

app = FastAPI(title="AgentField Apply Bot", version="0.1.0")

# Allow the Next.js dev server (port 3000) to hit the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path("data")
PROFILE_PATH = DATA_DIR / "profile.json"
HISTORY_PATH = DATA_DIR / "applications.json"
RESUME_PDF_PATH = DATA_DIR / "resume.pdf"


@app.on_event("startup")
async def _startup() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    # Allow seeding profile.json from an environment variable (cloud deploys
    # without persistent storage).  Set PROFILE_JSON to the full JSON string.
    if not PROFILE_PATH.exists():
        # PROFILE_JSON_B64: base64-encoded JSON — safe for all env var parsers.
        # PROFILE_JSON: raw JSON — fallback, may break Zeabur's raw var editor.
        seed_b64 = os.getenv("PROFILE_JSON_B64")
        seed = os.getenv("PROFILE_JSON")
        raw = None
        if seed_b64:
            try:
                raw = base64.b64decode(seed_b64).decode()
            except Exception:
                pass
        elif seed:
            raw = seed
        if raw:
            try:
                profile = CandidateProfile.model_validate_json(raw)
                PROFILE_PATH.write_text(profile.model_dump_json(indent=2))
            except Exception:
                pass  # bad env var — let the PUT endpoint handle it later


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def get_status() -> dict:
    return {
        "ok": True,
        "profile_configured": PROFILE_PATH.exists(),
        "resume_uploaded": RESUME_PDF_PATH.exists(),
        "history_entries": len(json.loads(HISTORY_PATH.read_text()))
        if HISTORY_PATH.exists()
        else 0,
        "actionbook_available": _find_actionbook() is not None,
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


@app.get("/api/profile")
async def get_profile() -> dict:
    if not PROFILE_PATH.exists():
        raise HTTPException(404, "Profile not found. Create data/profile.json first.")
    return json.loads(PROFILE_PATH.read_text())


class ProfileUpdate(BaseModel):
    model_config = {"extra": "allow"}


@app.put("/api/profile")
async def put_profile(body: dict) -> dict:
    # Validate against the schema before saving.
    try:
        profile = CandidateProfile.model_validate(body)
    except Exception as e:
        raise HTTPException(422, str(e))
    DATA_DIR.mkdir(exist_ok=True)
    PROFILE_PATH.write_text(profile.model_dump_json(indent=2))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Resume upload
# ---------------------------------------------------------------------------

_MAX_RESUME_BYTES = 20 * 1024 * 1024  # 20 MB


@app.post("/api/resume")
async def post_resume(file: UploadFile = File(...)) -> dict:
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        # Some browsers send application/octet-stream for PDFs — accept both
        # but reject anything obviously not a PDF by checking the filename too.
        name = file.filename or ""
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are accepted.")
    content = await file.read()
    if len(content) > _MAX_RESUME_BYTES:
        raise HTTPException(400, "File too large — maximum 20 MB.")
    DATA_DIR.mkdir(exist_ok=True)
    RESUME_PDF_PATH.write_bytes(content)
    return {"ok": True, "filename": file.filename, "size_bytes": len(content)}


# ---------------------------------------------------------------------------
# Job search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str
    sources: Optional[list[str]] = None
    max_per_source: int = 20


@app.post("/api/search")
async def post_search(req: SearchRequest) -> list[dict]:
    jobs = await search_jobs(
        req.query,
        sources=req.sources,
        max_per_source=req.max_per_source,
    )
    return [j.model_dump() for j in jobs]


@app.post("/api/search/debug")
async def post_search_debug(req: SearchRequest) -> dict:
    """Same as /api/search but returns per-source errors for debugging."""
    import asyncio
    from src.adapters.jobs.base import JobAdapter
    from src.reasoners.search_jobs import ADAPTERS

    sources = req.sources or list(ADAPTERS.keys())
    results: dict[str, dict] = {}

    async def _probe(name: str) -> None:
        adapter = ADAPTERS.get(name)
        if not adapter:
            results[name] = {"jobs": [], "error": "unknown source"}
            return
        try:
            jobs = await adapter.search(req.query, max_results=req.max_per_source)
            results[name] = {"jobs": [j.model_dump() for j in jobs], "error": None}
        except Exception as e:
            results[name] = {"jobs": [], "error": f"{type(e).__name__}: {e}"}

    await asyncio.gather(*[_probe(s) for s in sources])
    return results


# ---------------------------------------------------------------------------
# Application history
# ---------------------------------------------------------------------------


@app.get("/api/history")
async def get_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        raw = json.loads(HISTORY_PATH.read_text())
        return raw if isinstance(raw, list) else []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Apply (dry_run by default — change to false only for real submissions)
# ---------------------------------------------------------------------------


class ApplyRequest(BaseModel):
    job: dict
    dry_run: bool = True


@app.post("/api/apply")
async def post_apply(req: ApplyRequest) -> dict:
    # Validate profile exists and is complete.
    if not PROFILE_PATH.exists():
        raise HTTPException(400, "Profile not found. Fill in data/profile.json first.")

    profile_data = json.loads(PROFILE_PATH.read_text())
    try:
        profile = CandidateProfile.model_validate(profile_data)
    except Exception as e:
        raise HTTPException(400, f"Profile is invalid: {e}")

    bad = profile.has_unfilled_placeholders()
    if bad:
        raise HTTPException(400, f"Profile has unfilled placeholders: {bad}")

    if not RESUME_PDF_PATH.exists():
        raise HTTPException(400, "Resume PDF not found at data/resume.pdf.")

    try:
        job = JobPosting.model_validate(req.job)
    except Exception as e:
        raise HTTPException(422, f"Invalid job: {e}")

    # Actionbook is a local binary — not available in cloud containers.
    actionbook_bin = _find_actionbook()
    if not actionbook_bin:
        raise HTTPException(
            503,
            "Apply loop requires the Actionbook browser agent, which only runs "
            "on the local machine. Run the bot locally with `make start` to use this feature.",
        )

    # Full pipeline: parse resume → score → cover letter → apply.
    # All LLM calls are async; the browser loop is also async. This will
    # take 30–120 seconds — the frontend shows a spinner.
    from src.reasoners.parse_resume import parse_resume
    from src.reasoners.score_match import score_match
    from src.reasoners.tailor_cover_letter import tailor_cover_letter
    from src.reasoners.apply_to_job import apply_to_job
    from src.adapters.browser.actionbook_client import ActionbookClient

    parsed_resume = await parse_resume(RESUME_PDF_PATH)
    score = await score_match(parsed_resume, job)
    cover_letter = await tailor_cover_letter(parsed_resume, job, score)

    result = await apply_to_job(
        job=job,
        profile=profile,
        cover_letter=cover_letter,
        tailored_resume_pdf=RESUME_PDF_PATH,
        dry_run=req.dry_run,
        mode="local",
        client=ActionbookClient(binary=actionbook_bin),
    )

    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Next.js static files (must come LAST — catches everything else)
# ---------------------------------------------------------------------------

_STATIC_DIR = Path("frontend/out")

if _STATIC_DIR.exists():
    # Serve Next.js static export. html=True serves index.html for directory
    # requests, which handles client-side routing.
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
else:
    @app.get("/")
    async def dev_root() -> dict:
        return {
            "message": "API is running. Build the frontend with `cd frontend && npm run build` to serve the UI here.",
            "api_docs": "/docs",
        }
