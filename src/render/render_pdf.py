"""
render_pdf — produce PDF files from CoverLetter / TailoredResume objects.

NOT a reasoner. No LLM. No state. Pure transformation:
  Pydantic object + HTML template → PDF file on disk.

WHY THIS LIVES IN ITS OWN MODULE:
  The previous reasoners all share one pattern (LLM + schema). render_pdf
  is a different kind of operation entirely — templating + rendering.
  Keeping it separate keeps each module's mental model clean.

WHY HTML + CSS + WeasyPrint:
  - HTML/CSS is the most expressive layout tech we have access to
  - Jinja2 templates are reviewable as files, not buried in Python strings
  - WeasyPrint renders CSS print-mode well (@page, page-break, etc.)
  - When you eventually build the Next.js frontend, the same HTML templates
    can be shown in-browser before download (cohesion across the app).

FAILURE MODES TO KNOW ABOUT:
  WeasyPrint depends on system libs (Pango, cairo, gdk-pixbuf). If you see
  errors mentioning these, run:
      sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 \
                              libcairo2 libgdk-pixbuf-2.0-0
  The pip install of `weasyprint` alone is not enough on a fresh Ubuntu.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from src.schemas.cover_letter import CoverLetter
from src.schemas.resume import ParsedResume
from src.schemas.tailored_resume import TailoredResume


# Locate the templates folder relative to this file.
# So `python -m anything` works regardless of CWD.
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Jinja2 environment: autoescape protects against HTML injection in
# bullet text. Strip blocks keeps templates readable.
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_cover_letter_pdf(
    letter: CoverLetter,
    candidate: ParsedResume | TailoredResume,
    output_path: str | Path,
) -> Path:
    """
    Render a cover letter to PDF.

    Args:
        letter: the structured CoverLetter (from tailor_cover_letter)
        candidate: the resume the letter is for (used for sender header info:
                   name, email, phone, location, github, linkedin)
        output_path: where to write the PDF

    Returns:
        Path to the written file.
    """
    template = _env.get_template("cover_letter.html")
    html_str = template.render(
        letter=letter,
        candidate=candidate,
        today=date.today().strftime("%B %d, %Y"),
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(output_path))
    return output_path


def render_resume_pdf(
    resume: ParsedResume | TailoredResume,
    output_path: str | Path,
) -> Path:
    """
    Render a resume (parsed or tailored) to PDF.

    Both ParsedResume and TailoredResume have the same surface attributes
    used by the template, so we accept either.

    Args:
        resume: the resume to render
        output_path: where to write the PDF

    Returns:
        Path to the written file.
    """
    template = _env.get_template("resume.html")
    html_str = template.render(resume=resume)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(output_path))
    return output_path
