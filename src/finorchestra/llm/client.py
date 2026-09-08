"""LLM access through a single OpenAI-compatible chat-completions interface.

Providers
---------
- ``mock``: offline, deterministic. Never calls the network. Produces schema-valid JSON by applying a
  transparent heuristic to the numbers in the prompt (see `mock.py`). It exists so the full pipeline runs
  with no keys, and so the evaluation can be reproduced bit-for-bit.
- ``openai_compatible``: any endpoint speaking ``POST {base_url}/chat/completions`` with the OpenAI schema.
  Tested with Ollama; works unchanged with OpenAI, Cloudflare Workers AI, OpenRouter, and Bedrock behind an
  OpenAI-compatible gateway. Only ``base_url``, ``model``, and the API key env var change.

All calls go through `chat_json`, which asks for a JSON object, validates it against a pydantic model, and
retries with the validation error appended. On final failure it raises; callers decide whether to fall back.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from ..config import LLMCfg
from ..utils import LOG

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallStats:
    calls: int = 0
    failures: int = 0
    fallbacks: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "fallbacks_to_mock": self.fallbacks,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_latency_s": round(self.latency_s, 1),
            "sample_errors": self.errors[:5],
        }


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


class LLMClient:
    def __init__(self, cfg: LLMCfg):
        self.cfg = cfg
        self.stats = CallStats()
        self._mock = None
        if cfg.provider == "mock":
            from .mock import MockLLM

            self._mock = MockLLM()
        # key lookup: for api.openai.com prefer OPENAI_API_KEY (a leftover placeholder in the generic variable must
        # not shadow it); otherwise the configured variable; finally a placeholder that local servers ignore
        fallback = "OPENAI_API_KEY" if "openai.com" in cfg.base_url else None
        candidates = ([os.environ.get(fallback, "")] if fallback else []) + [os.environ.get(cfg.api_key_env, "")]
        self.api_key = next((k for k in candidates if k), "not-needed")
        if cfg.provider != "mock" and fallback and self.api_key == "not-needed":
            raise RuntimeError(
                f"No API key for {cfg.base_url}: put OPENAI_API_KEY=... (or {cfg.api_key_env}=...) in a .env file in the "
                "project root, or export it in the environment."
            )
        self.session = requests.Session()

    @property
    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.cfg.provider,
            "model": "deterministic-mock" if self.cfg.provider == "mock" else self.cfg.model,
            "base_url": None if self.cfg.provider == "mock" else self.cfg.base_url,
            "temperature": self.cfg.temperature,
            "declared_knowledge_cutoff": None if self.cfg.provider == "mock" else self.cfg.knowledge_cutoff,
        }

    # ------------------------------------------------------------------ core
    def chat(self, messages: list[dict[str, str]], json_mode: bool = True, task: str | None = None) -> str:
        if self._mock is not None:
            self.stats.calls += 1
            return self._mock.respond(messages, task=task)
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {"model": self.cfg.model, "messages": messages}
        # reasoning-model families (gpt-5*, o1/o3/o4) reject an explicit temperature; everything else gets the configured one
        if not re.match(r"^(gpt-5|o[1-9])", self.cfg.model):
            payload["temperature"] = self.cfg.temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        t0 = time.time()
        r = self.session.post(url, json=payload, headers=headers, timeout=self.cfg.timeout_s)
        self.stats.latency_s += time.time() - t0
        self.stats.calls += 1
        if r.status_code != 200:
            raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:300]}")
        js = r.json()
        usage = js.get("usage") or {}
        self.stats.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.stats.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        return js["choices"][0]["message"]["content"]

    def chat_json(self, messages: list[dict[str, str]], schema: type[T], task: str | None = None) -> T:
        msgs = list(messages)
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                raw = self.chat(msgs, json_mode=True, task=task)
                data = _extract_json(raw)
                return schema.model_validate(data)
            except (ValidationError, ValueError, json.JSONDecodeError, KeyError) as e:
                last_err = e
                self.stats.failures += 1
                self.stats.errors.append(f"{type(e).__name__}: {str(e)[:160]}")
                msgs = msgs + [
                    {"role": "assistant", "content": raw if "raw" in locals() else ""},
                    {
                        "role": "user",
                        "content": f"Your previous reply was not valid. Error: {str(e)[:400]}. "
                        "Reply again with ONLY a JSON object matching the requested schema.",
                    },
                ]
            except (requests.RequestException, RuntimeError) as e:
                last_err = e
                self.stats.failures += 1
                self.stats.errors.append(f"{type(e).__name__}: {str(e)[:160]}")
                time.sleep(1.0 + attempt)
        assert last_err is not None
        raise last_err

    def mock_fallback(self, messages: list[dict[str, str]], schema: type[T], task: str | None = None) -> T:
        """Deterministic stand-in used when the remote model fails; recorded in the certificate."""
        from .mock import MockLLM

        self.stats.fallbacks += 1
        LOG.warning("LLM: falling back to deterministic mock for task=%s", task)
        mock = MockLLM()
        return schema.model_validate(_extract_json(mock.respond(messages, task=task)))
