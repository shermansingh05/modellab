from modellab_adapters.base import ModelAdapter
from modellab_adapters.mock import MockAdapter
from modellab_adapters.ollama import OllamaAdapter
from modellab_adapters.vllm import VllmAdapter
from modellab_schemas import Backend, ModelEntry

__all__ = ["ModelAdapter", "MockAdapter", "OllamaAdapter", "VllmAdapter", "get_adapter"]


def get_adapter(entry: ModelEntry) -> ModelAdapter:
    if entry.backend == Backend.mock:
        return MockAdapter(entry)
    if entry.backend == Backend.ollama:
        return OllamaAdapter(entry)
    if entry.backend == Backend.vllm:
        return VllmAdapter(entry)
    from modellab_adapters.hf import TransformersAdapter

    return TransformersAdapter(entry)
