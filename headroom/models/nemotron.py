"""NVIDIA Nemotron via Nebius Token Factory.

Token Factory exposes an OpenAI-compatible chat completions API. Every call that
Headroom acts on asks for JSON matching a Pydantic schema, validates it, and on
failure sends the validation error back to the model for one more attempt.
"""

import json
import os
import re
import time
from collections.abc import Callable
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

TOKEN_FACTORY_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_MODEL = os.environ.get("NEMOTRON_MODEL", "")

T = TypeVar("T", bound=BaseModel)


class ModelOutputError(RuntimeError):
    pass


class ModelCall(BaseModel):
    """One inference call, kept for the run log and cost accounting."""

    task: str
    model: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    attempts: int


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply (drops reasoning tags, code fences, chatter)."""
    text = _THINK.sub("", text).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model output")
    return text[start : end + 1]


def _load_dotenv() -> None:
    """Minimal .env support so the key never has to be exported by hand."""
    path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class NemotronClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 180,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        _load_dotenv()
        self.api_key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not self.api_key:
            raise RuntimeError("NEBIUS_API_KEY is not set (add it to .env)")
        self.model = model or os.environ.get("NEMOTRON_MODEL") or DEFAULT_MODEL
        self.base_url = base_url or os.environ.get("NEBIUS_BASE_URL", TOKEN_FACTORY_URL)
        self.timeout = timeout
        self.transport = transport
        self.calls: list[ModelCall] = []
        # Told when each call starts and ends, so a live view can show the model working.
        self.on_call: Callable[[dict], None] = lambda _: None

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
            transport=self.transport,
        )

    async def list_models(self) -> list[str]:
        async with self._http() as http:
            response = await http.get("/models")
        response.raise_for_status()
        return sorted(m["id"] for m in response.json()["data"])

    async def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.2,
        max_tokens: int = 8192,
        retries: int = 1,
    ) -> T:
        if not self.model:
            raise RuntimeError("no model selected: set NEMOTRON_MODEL (see `headroom models`)")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
        }
        started = time.monotonic()
        prompt_tokens = completion_tokens = 0
        self.on_call({"task": task, "state": "start", "model": self.model})

        async with self._http() as http:
            for attempt in range(1, retries + 2):
                response = await http.post("/chat/completions", json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": response_format,
                })
                response.raise_for_status()
                body = response.json()
                usage = body.get("usage") or {}
                prompt_tokens += usage.get("prompt_tokens", 0)
                completion_tokens += usage.get("completion_tokens", 0)
                content = body["choices"][0]["message"].get("content") or ""

                try:
                    parsed = schema.model_validate_json(extract_json(content))
                except (ValueError, ValidationError) as exc:
                    error = str(exc)
                    messages += [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": (
                            "That reply did not match the required JSON schema:\n"
                            f"{error}\nReply again with only the corrected JSON object."
                        )},
                    ]
                    continue

                call = ModelCall(
                    task=task, model=self.model, latency_s=round(time.monotonic() - started, 2),
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, attempts=attempt,
                )
                self.calls.append(call)
                self.on_call({"state": "end", **call.model_dump()})
                return parsed

        self.on_call({"task": task, "state": "failed", "model": self.model,
                      "latency_s": round(time.monotonic() - started, 2)})
        raise ModelOutputError(f"{task}: no schema-valid output after {retries + 1} attempts: {error}")
