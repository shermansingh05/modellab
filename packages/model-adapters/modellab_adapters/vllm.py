"""Optional vLLM adapter over its OpenAI-compatible API. Only tested against a stubbed transport so far."""
from __future__ import annotations

import os
import time

import httpx

from modellab_adapters.base import ModelAdapter
from modellab_adapters.ollama import checked_base_url
from modellab_schemas import GenerationConfig, InferenceResult, Message, ModelEntry


class VllmAdapter(ModelAdapter):
    def __init__(self, entry: ModelEntry, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(entry)
        url = checked_base_url(base_url or os.environ.get("VLLM_URL", "http://127.0.0.1:8001"))
        self._client = httpx.Client(base_url=url, transport=transport)

    def generate(self, messages: list[Message], config: GenerationConfig) -> InferenceResult:
        start = time.perf_counter()
        body = {
            "model": self.entry.backend_model, "temperature": config.temperature, "top_p": config.top_p,
            "max_tokens": config.max_tokens, "seed": config.seed,
            "messages": [{"role": "user" if m.role == "tool" else m.role, "content": m.content} for m in messages],
        }
        try:
            resp = self._client.post("/v1/chat/completions", json=body, timeout=config.timeout_s)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return self._result(config, error=f"{type(exc).__name__}: {exc}", wall_ms=(time.perf_counter() - start) * 1000)
        wall = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {})
        completion = usage.get("completion_tokens")
        return self._result(
            config, text=data["choices"][0]["message"]["content"], prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=completion, wall_ms=wall, backend_version="vllm",
            tokens_per_s=completion / (wall / 1000) if completion else None,
        )

    def tokenize(self, text: str) -> None:
        return None

    def health_check(self) -> dict:
        try:
            ok = self._client.get("/health", timeout=5).status_code == 200
        except httpx.HTTPError as exc:
            return {"ok": False, "backend": "vllm", "detail": str(exc)}
        return {"ok": ok, "backend": "vllm"}
