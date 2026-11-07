"""Deterministic test fixture. It is not a model, and results from it say nothing about any real model.

It reads tool directives written as: call <tool> with {json}
- `obedient` follows directives found anywhere, including untrusted content. Stands in for a vulnerable agent.
- `cautious` only follows directives in the user's own turns, and declines disallowed requests.
"""
from __future__ import annotations

import json
import re
import time
import zlib

from modellab_adapters.base import ModelAdapter
from modellab_schemas import GenerationConfig, InferenceResult, Message

DIRECTIVE = re.compile(r"call\s+`?([a-z_]+\.[a-z_]+)`?\s+with\s+(\{.*?\})", re.S | re.I)
DISALLOWED_MARK = "[label:disallowed]"


class MockAdapter(ModelAdapter):
    @property
    def persona(self) -> str:
        return (self.entry.backend_model or "cautious").removeprefix("mock-")

    def generate(self, messages: list[Message], config: GenerationConfig) -> InferenceResult:
        start = time.perf_counter()
        text = self._respond(messages)
        wall = (time.perf_counter() - start) * 1000
        prompt_tokens = sum(len(m.content.split()) for m in messages)
        completion = len(text.split())
        return self._result(
            config, text=text, backend_version="mock-1", prompt_tokens=prompt_tokens, completion_tokens=completion,
            wall_ms=wall, ttft_ms=wall, tokens_per_s=completion / max(wall / 1000, 1e-6),
        )

    def _respond(self, messages: list[Message]) -> str:
        users = [m.content for m in messages if m.role == "user"]
        joined = "\n".join(users)
        if DISALLOWED_MARK in joined and self.persona == "cautious":
            return "I can't help with that request."
        untrusted = ("system", "user", "tool")
        scope = [m.content for m in messages if m.role in untrusted] if self.persona == "obedient" else users
        done = {m.content for m in messages if m.role == "assistant"}
        for block in scope:
            for tool, raw in DIRECTIVE.findall(block):
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                call = json.dumps({"tool": tool, "args": args}, sort_keys=True)
                if call not in done:
                    return call
        results = " ".join(m.content for m in messages if m.role == "tool")
        return f"Done. {results}".strip() if results else "Here is a direct answer to your request."

    def tokenize(self, text: str) -> list[int]:
        return [zlib.crc32(w.encode()) % 50257 for w in text.split()]  # Stable across processes, unlike hash().

    def health_check(self) -> dict:
        return {"ok": True, "backend": "mock", "detail": f"deterministic fixture ({self.persona})"}
