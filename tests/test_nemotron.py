import json

import httpx
import pytest
from pydantic import BaseModel

from headroom.models.nemotron import ModelOutputError, NemotronClient, extract_json


class Verdict(BaseModel):
    verdict: str
    confidence: float


def _reply(content: str, prompt_tokens: int = 10, completion_tokens: int = 5) -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _client(replies: list[dict], seen: list[dict]) -> NemotronClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    return NemotronClient(api_key="test-key", model="nvidia/nemotron-test", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "raw",
    [
        '{"verdict": "supported", "confidence": 0.9}',
        '```json\n{"verdict": "supported", "confidence": 0.9}\n```',
        '<think>lock wait dominates</think>\n{"verdict": "supported", "confidence": 0.9}',
        'Here is my answer:\n{"verdict": "supported", "confidence": 0.9}\nThanks.',
    ],
)
def test_extract_json_tolerates_wrappers(raw):
    assert json.loads(extract_json(raw)) == {"verdict": "supported", "confidence": 0.9}


async def test_complete_json_validates_against_schema():
    seen: list[dict] = []
    client = _client([_reply('{"verdict": "disproved", "confidence": 0.8}')], seen)

    result = await client.complete_json(task="conclude", system="sys", user="usr", schema=Verdict)

    assert result == Verdict(verdict="disproved", confidence=0.8)
    request = seen[0]
    assert request["model"] == "nvidia/nemotron-test"
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["schema"]["title"] == "Verdict"
    assert client.calls[0].task == "conclude"
    assert client.calls[0].prompt_tokens == 10


async def test_complete_json_repairs_invalid_output():
    seen: list[dict] = []
    client = _client([_reply('{"verdict": "supported"}'), _reply('{"verdict": "supported", "confidence": 0.7}')], seen)

    result = await client.complete_json(task="conclude", system="sys", user="usr", schema=Verdict)

    assert result.confidence == 0.7
    assert len(seen) == 2
    repair = seen[1]["messages"][-1]["content"]
    assert "confidence" in repair and "schema" in repair.lower()


async def test_complete_json_gives_up_after_retries():
    seen: list[dict] = []
    client = _client([_reply("not json at all")] * 3, seen)

    with pytest.raises(ModelOutputError):
        await client.complete_json(task="conclude", system="sys", user="usr", schema=Verdict, retries=2)

    assert len(seen) == 3


def test_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here to fall back on

    with pytest.raises(RuntimeError, match="NEBIUS_API_KEY"):
        NemotronClient()


async def test_reports_each_call_as_it_starts_and_ends():
    seen, calls = [], []
    client = _client([_reply('{"verdict": "supported", "confidence": 0.9}', 120, 30)], seen)
    client.on_call = calls.append

    await client.complete_json(task="conclude", system="s", user="u", schema=Verdict)

    assert [c["state"] for c in calls] == ["start", "end"]
    assert calls[0] == {"task": "conclude", "state": "start", "model": "nvidia/nemotron-test"}
    assert calls[1]["prompt_tokens"] == 120 and calls[1]["completion_tokens"] == 30
    assert calls[1]["latency_s"] >= 0


async def test_reports_a_failed_call():
    calls = []
    client = _client([_reply("not json"), _reply("still not json")], [])
    client.on_call = calls.append

    with pytest.raises(ModelOutputError):
        await client.complete_json(task="conclude", system="s", user="u", schema=Verdict)

    assert [c["state"] for c in calls] == ["start", "failed"]
