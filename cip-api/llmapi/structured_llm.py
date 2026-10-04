"""
Structured LLM calls with retry (the sdlc-api `retry_invoke` pattern).

    result = await ask_structured(llm, RepoPlan, system, human, on_retry=callback)

Returns a Pydantic object, or None when there is no LLM or every attempt failed – callers then fall back to rules.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def ask_structured(llm, schema: Type[T], system: str, human: str, retries: int = 2,
                         on_retry: Optional[Callable[[int, Exception], Awaitable[None]]] = None) -> Optional[T]:
    """Invoke the LLM with a structured-output schema; exponential backoff between attempts."""
    if llm is None:
        return None
    runnable = llm.with_structured_output(schema)
    for attempt in range(1, retries + 2):
        try:
            return await runnable.ainvoke([SystemMessage(content=system), HumanMessage(content=human[:120_000])])
        except Exception as e:  # noqa: BLE001
            logging.warning("[LLM] %s attempt %d failed: %s", schema.__name__, attempt, e)
            if attempt > retries:
                return None
            if on_retry:
                await on_retry(attempt, e)
            await asyncio.sleep(2 ** attempt)
    return None
