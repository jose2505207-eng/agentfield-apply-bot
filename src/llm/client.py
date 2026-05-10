"""
Provider-agnostic LLM client.

The day of the hackathon you'll swap providers by changing ONE env var:
  LLM_PROVIDER=openai  (default, dev)
  LLM_PROVIDER=qwen    (sponsor, hackathon day)
  LLM_PROVIDER=zai     (sponsor, hackathon day)

Reasoners NEVER import openai/anthropic/qwen directly.
They only call structured_complete() from this module.
"""
from __future__ import annotations
import os
from typing import Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def structured_complete(
    schema: Type[T],
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.0,
) -> T:
    """
    Call the configured LLM provider and return a parsed Pydantic instance.

    Args:
        schema: Pydantic BaseModel class describing the expected output shape.
        system: System prompt.
        user: User prompt (typically the content to analyze).
        model: Override the default model for this provider.
        temperature: Sampling temperature.

    Returns:
        Instance of `schema` with all fields populated.
    """
    provider = os.getenv("LLM_PROVIDER", "openai").lower()

    if provider == "openai":
        from .providers.openai_provider import complete as openai_complete
        return await openai_complete(schema, system, user, model=model, temperature=temperature)

    # Hackathon-day providers — implement when you swap
    # if provider == "qwen":
    #     from .providers.qwen_provider import complete as qwen_complete
    #     return await qwen_complete(schema, system, user, model=model, temperature=temperature)
    # if provider == "zai":
    #     from .providers.zai_provider import complete as zai_complete
    #     return await zai_complete(schema, system, user, model=model, temperature=temperature)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}")
