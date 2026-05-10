"""
parse_resume reasoner.

Input:  path to a resume PDF
Output: ParsedResume (Pydantic instance)

This is reasoner #1 of the apply-bot pipeline. The output is consumed by:
  - score_match  (compares resume to a job description)
  - tailor_cover_letter  (rewrites cover letter using resume facts)
  - tailor_resume  (rewrites resume bullets per role)
"""
from __future__ import annotations
from pathlib import Path
from pypdf import PdfReader

from src.llm.client import structured_complete
from src.schemas.resume import ParsedResume


SYSTEM_PROMPT = """You are a resume parser. You will be given the full text content of a resume PDF.
Your job is to extract structured data accurately and faithfully.

Rules:
- Copy bullets verbatim. Do NOT paraphrase, summarize, or "improve" them.
- If a field is missing from the resume, leave it null/empty rather than inventing.
- For dates, preserve the original format (e.g. "2024 - Present", "Jan 2024").
- For skills, group them under the categories the resume itself uses.
  If the resume has flat skills, put them all under "General".
- Extract URLs (LinkedIn, GitHub) only if explicitly present.
- The "summary" field should be the resume's professional summary section, not your interpretation.
"""


def _extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract all text from a PDF, page by page."""
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


async def parse_resume(pdf_path: str | Path) -> ParsedResume:
    """
    Parse a resume PDF into a structured ParsedResume.

    Args:
        pdf_path: Path to the resume PDF file.

    Returns:
        ParsedResume with all available fields populated.

    Raises:
        FileNotFoundError: If the PDF doesn't exist.
        RuntimeError: If the LLM fails to return a valid parse.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"Resume PDF not found: {pdf_path}")

    raw_text = _extract_pdf_text(pdf_path)
    if not raw_text:
        raise RuntimeError(f"PDF appears to be empty or unreadable: {pdf_path}")

    user_prompt = f"Resume text:\n\n---\n{raw_text}\n---\n\nReturn the structured ParsedResume."

    return await structured_complete(
        schema=ParsedResume,
        system=SYSTEM_PROMPT,
        user=user_prompt,
    )
