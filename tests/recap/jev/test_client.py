"""JevClient: ordering, token accounting, SDK error mapping."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
import pytest
from typesafe_sdk import (
    Noul,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAuthenticationError,
    TypeSafeError,
    TypeSafeRateLimitError,
)

from news_recap.recap.exceptions import RecapPipelineError
from news_recap.recap.jev import client as client_module
from news_recap.recap.jev.client import JevClient, JevUnavailableError, make_jev_client

_QUESTIONS = {"q": Noul(instructions="Is this about billing?")}


def _response(p: float, tokens: int) -> SystemOneResponse:
    return SystemOneResponse.model_validate(
        {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": tokens, "output_tokens": 1},
            "answers": {"q": {"type": "noul", "noul": p}},
        }
    )


class _FakeAsyncClient:
    """Stands in for AsyncTypeSafeClient; *answer* maps state → response or exception."""

    instances: list[_FakeAsyncClient] = []

    def __init__(self, answer, **kwargs) -> None:
        self.answer = answer
        self.kwargs = kwargs
        self.in_flight = 0
        self.max_in_flight = 0
        self.closed = False
        _FakeAsyncClient.instances.append(self)

    async def system_one(self, *, state, questions):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01 * (state % 3))
            result = self.answer(state)
            if isinstance(result, BaseException):
                raise result
            return result
        finally:
            self.in_flight -= 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch):
    _FakeAsyncClient.instances = []

    def install(answer):
        monkeypatch.setattr(
            client_module,
            "AsyncTypeSafeClient",
            lambda **kwargs: _FakeAsyncClient(answer, **kwargs),
        )

    return install


def test_decide_keeps_request_order_and_counts_tokens(fake_sdk) -> None:
    fake_sdk(lambda state: _response(state / 10, tokens=100 + state))
    client = JevClient("key", "jev-1.13.0", max_concurrency=2)

    responses = client.decide([(i, _QUESTIONS) for i in range(6)])

    assert [r.nouls["q"].noul for r in responses] == [i / 10 for i in range(6)]
    assert client.input_tokens == sum(100 + i for i in range(6))
    assert client.requests == 6
    fake = _FakeAsyncClient.instances[0]
    assert fake.kwargs == {"api_key": "key", "model": "jev-1.13.0"}
    assert fake.max_in_flight <= 2
    assert fake.closed


def test_decide_accumulates_across_calls(fake_sdk) -> None:
    fake_sdk(lambda state: _response(0.5, tokens=10))
    client = JevClient("key", "jev-1.13.0")
    client.decide([(1, _QUESTIONS)])
    client.decide([(2, _QUESTIONS), (3, _QUESTIONS)])
    assert (client.input_tokens, client.requests) == (30, 3)


def test_decide_empty_makes_no_request(fake_sdk) -> None:
    fake_sdk(lambda state: _response(0.5, tokens=10))
    assert JevClient("key", "jev-1.13.0").decide([]) == []
    assert _FakeAsyncClient.instances == []


_HEADERS = httpx2.Headers()


@pytest.mark.parametrize(
    "error",
    [
        TypeSafeAuthenticationError(401, {"error": "bad key"}, _HEADERS),
        TypeSafeRateLimitError(429, {"error": "slow down"}, _HEADERS),
        TypeSafeAPIConnectionError("Connection error: refused"),
        TypeSafeError("The request body could not be encoded as JSON"),
    ],
    ids=["auth", "rate-limit", "connection", "base"],
)
def test_sdk_errors_map_to_jev_unavailable(fake_sdk, error: TypeSafeError) -> None:
    fake_sdk(lambda state: error if state == 2 else _response(0.5, tokens=10))
    client = JevClient("key", "jev-1.13.0")

    with pytest.raises(JevUnavailableError) as raised:
        client.decide([(i, _QUESTIONS) for i in range(4)])

    assert isinstance(raised.value, RecapPipelineError)
    assert raised.value.__cause__ is error
    assert type(error).__name__ in str(raised.value)


def test_other_errors_are_not_mapped(fake_sdk) -> None:
    fake_sdk(lambda state: ValueError("bug"))
    with pytest.raises(ExceptionGroup):
        JevClient("key", "jev-1.13.0").decide([(1, _QUESTIONS)])


def test_make_jev_client_without_key_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert make_jev_client(tmp_path, "jev-1.13.0") is None

    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=k\n")
    client = make_jev_client(tmp_path, "jev-1.13.0")
    assert client is not None
    assert client.model == "jev-1.13.0"
