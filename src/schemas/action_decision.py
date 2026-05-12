"""
ActionDecision schema.

What the LLM outputs at each step of the apply_to_job loop:

  for step in range(max_steps):
      snapshot = await actionbook.snapshot(session)
      decision = await structured_complete(schema=ActionDecision, ...)
      if decision.kind == "done":  return success
      if decision.kind == "stuck": return needs_human
      await actionbook_execute(decision, session)

WHY DISCRIMINATED UNION (kind: Literal[...]):
  Early prototype tried treating actions as free-form natural language
  ("click the apply button"). The LLM kept hallucinating selectors that
  didn't exist. Pinning it to ~9 verbs against actual refs in the snapshot
  forces the LLM to use what's actually there. Same principle as the
  BulletChange audit pattern in TailoredResume.

WHY confidence FIELD:
  When the LLM is "low" confidence on a destructive action (submit, upload),
  apply_to_job aborts to manual review instead of executing. Cheap insurance
  against confident-looking but wrong decisions.

WHY is_terminal SELF-ATTESTATION:
  Same idea as `key_evidence_used` in CoverLetter — the LLM declares the
  meaning of its own output. We can validate consistency: if kind=='submit'
  but is_terminal=True, that's a contradiction and we reject the decision.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


ActionKind = Literal[
    "click",     # click a ref from the snapshot
    "fill",      # type text into a text input or textarea
    "select",    # choose an option in a <select> dropdown
    "upload",    # attach a file to a file input
    "wait",      # pause N seconds for page to settle (after navigation / dynamic load)
    "scroll",    # scroll down the page to expose more content in the next snapshot
    "submit",    # the final submit click — the moment of truth
    "done",      # form was already submitted; we observe a confirmation page
    "stuck",     # captcha / login wall / unknown field / ambiguity → hand off to human
]


class ActionDecision(BaseModel):
    """One step the LLM chooses to execute in the apply loop."""

    kind: ActionKind = Field(description="What kind of action to perform")

    ref: Optional[str] = Field(
        description="Accessibility ref from the snapshot (e.g. '@e5'). "
                    "REQUIRED when kind is click, fill, select, or upload. "
                    "Null when kind is wait, scroll, submit (re-uses last ref), done, or stuck."
    )

    value: Optional[str] = Field(
        description="Payload for the action:\n"
                    "  - kind='fill'   → text to type into the input\n"
                    "  - kind='select' → option label/value to choose\n"
                    "  - kind='upload' → ABSOLUTE path to the file to attach\n"
                    "  - kind='wait'   → number of seconds (as a string, e.g. '2')\n"
                    "Null for click / scroll / submit / done / stuck."
    )

    reasoning: str = Field(
        description="One sentence explaining WHY this action right now, "
                    "citing what in the snapshot motivated it. Audit trail."
    )

    confidence: Literal["high", "medium", "low"] = Field(
        description="LLM's confidence in this decision. "
                    "If 'low' on a destructive kind (submit, upload), "
                    "apply_to_job aborts and tags the result as needs-manual-review."
    )

    is_terminal: bool = Field(
        description="True ONLY when kind is 'done' or 'stuck'. "
                    "False for every intermediate action including 'submit'. "
                    "(submit may succeed and lead to a confirmation page, "
                    "which the NEXT decision should detect as 'done'.)"
    )
