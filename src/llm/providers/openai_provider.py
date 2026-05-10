"""
OpenAI provider — uses native structured outputs (Pydantic schema in, instance out).
"""
from __future__ import annotations
import os
from typing import Type, TypeVar
from pydantic import BaseModel
from openai import AsyncOpenAI

T = TypeVar("T", bound=BaseModel)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment")
        _client = AsyncOpenAI(api_key=api_key)
    return _client


async def complete(
    schema: Type[T],
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.0,
) -> T:
    """
    Use OpenAI's structured outputs API to get a Pydantic instance directly.
    Falls back to gpt-4o-mini if no model specified — fast and cheap for development.
    """
    client = _get_client()
    chosen_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    completion = await client.beta.chat.completions.parse(
        model=chosen_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=schema,
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        # Either refusal or schema validation failure
        refusal = completion.choices[0].message.refusal
        raise RuntimeError(f"OpenAI returned no parsed object. Refusal: {refusal!r}")

    return parsed
