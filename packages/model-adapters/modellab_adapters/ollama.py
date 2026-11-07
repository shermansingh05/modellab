"""Ollama over its local HTTP API. Refuses non-loopback hosts unless explicitly allowed."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from urllib.parse import urlparse

import httpx

from modellab_adapters.base import ModelAdapter
from modellab_schemas import GenerationConfig, InferenceResult, Message, ModelEntry

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def checked_base_url(url: str) -> str:
    host = urlparse(url).hostname
    if host not in LOOPBACK and os.environ.get("MODELLAB_ALLOW_REMOTE_INFERENCE") != "1":
        raise ValueError(f"refusing non-loopback inference host {host!r}; set MODELLAB_ALLOW_REMOTE_INFERENCE=1")
    return url.rstrip("/")


class OllamaAdapter(ModelAdapter):
    def __init__(self, entry: ModelEntry, base_url: str | None = None, transport: httpx.BaseTransport | None = None):
        super().__init__(entry)
        self.base_url = checked_base_url(base_url or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
        self._client = httpx.Client(base_url=self.base_url, transport=transport, timeout=30)

    def _payload(self, messages: list[Message], config: GenerationConfig, stream: bool) -> dict:
        options = {"temperature": config.temperature, "top_p": config.top_p, "num_predict": config.max_tokens,
                   "num_ctx": self.entry.context_window}
        if config.seed is not None:
            options["seed"] = config.seed
        # A tool role would need Ollama's native tool protocol, so tool results go back as labeled user turns.
        msgs = [{"role": "user" if m.role == "tool" else m.role,
                 "content": f"[TOOL RESULT]\n{m.content}" if m.role == "tool" else m.content} for m in messages]
        return {"model": self.entry.backend_model, "messages": msgs, "stream": stream, "options": options,
                "think": config.thinking, "keep_alive": "10m"}

    def version(self) -> str | None:
        try:
            return self._client.get("/api/version", timeout=5).json().get("version")
        except (httpx.HTTPError, ValueError):
            return None

    def generate(self, messages: list[Message], config: GenerationConfig) -> InferenceResult:
        start = time.perf_counter()
        ttft = None
        parts: list[str] = []
        final: dict = {}
        timeout = httpx.Timeout(config.timeout_s, connect=5)
        try:
            with self._client.stream("POST", "/api/chat", json=self._payload(messages, config, True),
                                     timeout=timeout) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise httpx.HTTPStatusError(resp.text[:300], request=resp.request, response=resp)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        ttft = ttft if ttft is not None else (time.perf_counter() - start) * 1000
                        parts.append(piece)
                    if time.perf_counter() - start > config.timeout_s:
                        raise TimeoutError(f"generation exceeded {config.timeout_s}s")
                    if chunk.get("done"):
                        final = chunk
        except (httpx.HTTPError, TimeoutError, ValueError) as exc:
            return self._result(config, error=f"{type(exc).__name__}: {exc}", backend_version=self.version(),
                                wall_ms=(time.perf_counter() - start) * 1000, text="".join(parts))
        wall = (time.perf_counter() - start) * 1000
        eval_ns = final.get("eval_duration") or 0
        completion = final.get("eval_count")
        return self._result(
            config, text="".join(parts), backend_version=self.version(), prompt_tokens=final.get("prompt_eval_count"),
            completion_tokens=completion, wall_ms=wall, ttft_ms=ttft,
            tokens_per_s=(completion / (eval_ns / 1e9)) if completion and eval_ns else None,
            gpu_memory_mb=self._vram_mb(),
        )

    def stream_generate(self, messages: list[Message], config: GenerationConfig) -> Iterator[str]:
        with self._client.stream("POST", "/api/chat", json=self._payload(messages, config, True),
                                 timeout=httpx.Timeout(config.timeout_s, connect=5)) as resp:
            for line in resp.iter_lines():
                if line:
                    piece = json.loads(line).get("message", {}).get("content", "")
                    if piece:
                        yield piece

    def _vram_mb(self) -> float | None:
        try:
            for m in self._client.get("/api/ps", timeout=5).json().get("models", []):
                if m.get("name") == self.entry.backend_model:
                    return m.get("size_vram", 0) / (1024 * 1024)
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def tokenize(self, text: str) -> None:
        return None  # Ollama exposes no tokenizer endpoint.

    def load_model(self) -> None:
        self._client.post("/api/chat", json={"model": self.entry.backend_model, "messages": [], "keep_alive": "10m"},
                          timeout=120)

    def unload_model(self) -> None:
        self._client.post("/api/chat", json={"model": self.entry.backend_model, "messages": [], "keep_alive": 0},
                          timeout=30)

    def pull(self) -> Iterator[dict]:
        with self._client.stream("POST", "/api/pull", json={"name": self.entry.backend_model}, timeout=None) as r:
            for line in r.iter_lines():
                if line:
                    yield json.loads(line)

    def artifact_digest(self) -> str | None:
        try:
            for m in self._client.get("/api/tags", timeout=5).json().get("models", []):
                if m.get("name") == self.entry.backend_model:
                    return m.get("digest")
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def details(self) -> dict:
        resp = self._client.post("/api/show", json={"model": self.entry.backend_model}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("details", {})

    def health_check(self) -> dict:
        version = self.version()
        if version is None:
            return {"ok": False, "backend": "ollama", "detail": f"no Ollama server at {self.base_url}"}
        digest = self.artifact_digest()
        if digest is None:
            return {"ok": False, "backend": "ollama", "version": version, "detail": "model not pulled"}
        return {"ok": True, "backend": "ollama", "version": version, "digest": digest}
