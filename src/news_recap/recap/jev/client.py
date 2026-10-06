"""Batched Jev requests over the async TypeSafe SDK."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path

from typesafe_sdk import (
    AsyncTypeSafeClient,
    JSONContent,
    Question,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeError,
)

from news_recap.config import resolve_typesafe_api_key
from news_recap.recap.exceptions import RecapPipelineError

MAX_CONCURRENCY = 16
# One request failing after its retries sends the whole step to its LLM path (agy launches), so
# retry longer than the SDK's default of 2.
_RETRY = RetryPolicy(max_retries=5)

JevRequest = tuple[JSONContent, Mapping[str, Question]]


class JevUnavailableError(RecapPipelineError):
    """Jev could not answer after the SDK's retries."""

    def __init__(self, message: str) -> None:
        super().__init__("jev", message)


class JevClient:
    """Answers many independent Jev requests concurrently and counts billed tokens."""

    def __init__(self, api_key: str, model: str, max_concurrency: int = MAX_CONCURRENCY) -> None:
        self._api_key = api_key
        self.model = model
        self.max_concurrency = max_concurrency
        self.input_tokens = 0
        self.requests = 0

    def decide(self, requests: Sequence[JevRequest]) -> list[SystemOneResponse]:
        """Return one response per request, in request order."""
        if not requests:
            return []
        try:
            return asyncio.run(self._decide_all(requests))
        except* JevUnavailableError as group:
            raise group.exceptions[0] from None
        except* TypeSafeError as group:
            error = group.exceptions[0]
            raise JevUnavailableError(f"{type(error).__name__}: {error}") from error

    async def _decide_all(self, requests: Sequence[JevRequest]) -> list[SystemOneResponse]:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        async with AsyncTypeSafeClient(
            api_key=self._api_key,
            model=self.model,
            retry=_RETRY,
        ) as client:

            async def one(state: JSONContent, questions: Mapping[str, Question]):
                async with semaphore:
                    response = await client.system_one(state=state, questions=questions)
                self.input_tokens += response.usage.input_tokens or 0
                self.requests += 1
                # The SDK drops answers of types it does not model.
                if missing := sorted(set(questions) - set(response.answers)):
                    raise JevUnavailableError(f"no answer to {', '.join(missing)}")
                return response

            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(one(state, qs)) for state, qs in requests]
        return [task.result() for task in tasks]


def make_jev_client(data_dir: Path, model: str) -> JevClient | None:
    """Return a client when a TypeSafe API key is configured, else ``None``."""
    api_key = resolve_typesafe_api_key(data_dir)
    return JevClient(api_key, model) if api_key else None
