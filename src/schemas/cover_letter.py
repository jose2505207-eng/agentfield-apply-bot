"""
CoverLetter schema.

Output of tailor_cover_letter. Consumed by render_pdf (which renders it to
a real PDF the bot will attach to applications) and by the frontend (which
shows it to the user for review before sending).

WHY STRUCTURED INSTEAD OF A SINGLE STRING:
  - render_pdf needs greeting on its own line, paragraphs separated, sign-off
    formatted. A single string would force the renderer to re-parse text.
  - The frontend lets the user edit individual paragraphs. A single string
    would force a single textarea instead of editable cards.
  - key_evidence_used is our anti-hallucination check: the LLM must declare
    which specific resume facts grounded each claim. We can verify these
    actually exist in the resume before sending.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class CoverLetter(BaseModel):
    """A tailored cover letter for a specific job application."""

    subject: str = Field(
        description="Email subject line. Format: 'Application for {role} at {company}'"
    )
    greeting: str = Field(
        description="Opening salutation. Use 'Dear Hiring Team at {company},' "
                    "when no specific recipient is known."
    )
    body_paragraphs: list[str] = Field(
        description="Exactly 3 paragraphs: (1) hook stating the role and why "
                    "applying, (2) evidence paragraph tying specific resume "
                    "facts to job requirements, (3) closing with availability "
                    "and call to action."
    )
    sign_off: str = Field(
        description="Closing line + name. Format: 'Sincerely,\\n{full_name}'"
    )

    tone: Literal["formal", "professional", "warm", "casual"] = Field(
        description="The tone the LLM aimed for. Sanity check we can validate."
    )

    key_evidence_used: list[str] = Field(
        description="Specific resume facts (job titles, project names, skills, "
                    "achievements) cited in the letter. Used as a groundedness "
                    "check: every claim should map to evidence here. "
                    "If empty, the letter is ungrounded and should be rejected."
    )
