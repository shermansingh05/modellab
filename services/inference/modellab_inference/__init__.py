"""The single inference entry point, which strips reasoning blocks and records comparable metadata."""
from __future__ import annotations

import re

from modellab_adapters import ModelAdapter
from modellab_observability import tracer
from modellab_schemas import GenerationConfig, InferenceResult, Message

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def run_inference(adapter: ModelAdapter, messages: list[Message], config: GenerationConfig) -> InferenceResult:
    with tracer.start_as_current_span("inference") as span:
        span.set_attribute("model.id", adapter.entry.id)
        result = adapter.generate(messages, config)
        result.text = THINK_RE.sub("", result.text).strip()
        span.set_attribute("tokens.completion", result.completion_tokens or 0)
        return result
