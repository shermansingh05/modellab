"""The adapter contract. Every backend records the same fields."""
from __future__ import annotations

import abc
import platform
import resource
import sys
from collections.abc import Iterator

from modellab_schemas import GenerationConfig, InferenceResult, Message, ModelEntry


def hardware_label() -> str:
    return f"{platform.system()}-{platform.machine()}"


def peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


class ModelAdapter(abc.ABC):
    def __init__(self, entry: ModelEntry):
        self.entry = entry

    def load_model(self) -> None:  # noqa: B027
        """Load or connect. Optional for backends that manage their own lifecycle."""

    def unload_model(self) -> None:  # noqa: B027
        """Release resources."""

    @abc.abstractmethod
    def generate(self, messages: list[Message], config: GenerationConfig) -> InferenceResult: ...

    def generate_batch(self, batch: list[list[Message]], config: GenerationConfig) -> list[InferenceResult]:
        return [self.generate(m, config) for m in batch]

    def stream_generate(self, messages: list[Message], config: GenerationConfig) -> Iterator[str]:
        yield self.generate(messages, config).text

    @abc.abstractmethod
    def tokenize(self, text: str) -> list[int] | None:
        """Token IDs, or None when the backend does not expose a tokenizer."""

    @abc.abstractmethod
    def health_check(self) -> dict: ...

    def get_runtime_metrics(self) -> dict:
        return {"peak_rss_mb": peak_rss_mb(), "hardware": hardware_label()}

    def _result(self, config: GenerationConfig, **kw) -> InferenceResult:
        fields = {
            "model_id": self.entry.id, "backend": self.entry.backend.value, "revision": self.entry.revision,
            "quantization": self.entry.quantization, "hardware": hardware_label(),
            "template_version": self.entry.chat_template_id, "config": config, "peak_rss_mb": peak_rss_mb(),
        }
        fields.update(kw)
        return InferenceResult(**fields)
