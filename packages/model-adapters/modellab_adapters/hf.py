"""Hugging Face Transformers. Needs the `ml` extra. Remote code is never trusted, and revisions are pinned."""
from __future__ import annotations

import threading
import time

from modellab_adapters.base import ModelAdapter
from modellab_schemas import GenerationConfig, InferenceResult, Message

SAFE_PATTERNS = ["*.safetensors", "*.json", "*.txt", "tokenizer.model", "*.jinja"]


def download(repo: str, revision: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, revision=revision, allow_patterns=SAFE_PATTERNS)


class TransformersAdapter(ModelAdapter):
    def __init__(self, entry):
        super().__init__(entry)
        self.model = None
        self.tokenizer = None
        self.device = None

    def load_model(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        common = dict(revision=self.entry.revision, trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(self.entry.hf_repo, **common)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.entry.hf_repo, use_safetensors=True, torch_dtype="auto", **common
        ).to(self.device).eval()

    def unload_model(self) -> None:
        self.model = self.tokenizer = None

    def _encode(self, messages: list[Message], config: GenerationConfig):
        msgs = [{"role": "user" if m.role == "tool" else m.role, "content": m.content} for m in messages]
        if getattr(self.tokenizer, "chat_template", None):
            kwargs = {"enable_thinking": config.thinking} if "enable_thinking" in (self.tokenizer.chat_template or "") else {}
            prompt = self.tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, **kwargs)
        else:
            prompt = "\n".join(f"{m['role']}: {m['content']}" for m in msgs) + "\nassistant:"
        return self.tokenizer(prompt, return_tensors="pt").to(self.device)

    def _kwargs(self, config: GenerationConfig) -> dict:
        kw = dict(max_new_tokens=config.max_tokens, pad_token_id=self.tokenizer.eos_token_id)
        if config.temperature > 0:
            kw.update(do_sample=True, temperature=config.temperature, top_p=config.top_p)
        else:
            kw.update(do_sample=False)
        return kw

    def generate(self, messages: list[Message], config: GenerationConfig) -> InferenceResult:
        import torch
        import transformers

        if self.model is None:
            self.load_model()
        if config.seed is not None:
            torch.manual_seed(config.seed)
        inputs = self._encode(messages, config)
        streamer = transformers.TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        start = time.perf_counter()
        errors: list[Exception] = []

        def work() -> None:
            try:
                self.model.generate(**inputs, streamer=streamer, **self._kwargs(config))
            except Exception as exc:  # noqa: BLE001 - reported on the result
                errors.append(exc)
                streamer.end()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        ttft = None
        parts: list[str] = []
        for piece in streamer:
            if piece and ttft is None:
                ttft = (time.perf_counter() - start) * 1000
            parts.append(piece)
        thread.join()
        wall = (time.perf_counter() - start) * 1000
        text = "".join(parts)
        completion = len(self.tokenizer(text, add_special_tokens=False).input_ids)
        gpu = None
        if self.device == "cuda":
            gpu = torch.cuda.max_memory_allocated() / (1024 * 1024)
        elif self.device == "mps":
            gpu = torch.mps.driver_allocated_memory() / (1024 * 1024)
        return self._result(
            config, text=text, backend_version=f"transformers-{transformers.__version__}",
            prompt_tokens=int(inputs.input_ids.shape[-1]), completion_tokens=completion, wall_ms=wall, ttft_ms=ttft,
            tokens_per_s=completion / max(wall / 1000, 1e-6), gpu_memory_mb=gpu,
            hardware=f"{self.device}", error=str(errors[0]) if errors else None,
        )

    def tokenize(self, text: str) -> list[int]:
        if self.tokenizer is None:
            self.load_model()
        return self.tokenizer(text).input_ids

    def health_check(self) -> dict:
        try:
            import torch
            import transformers
        except ImportError:
            return {"ok": False, "backend": "transformers", "detail": "install the ml extra: uv sync --extra ml"}
        return {"ok": True, "backend": "transformers", "version": transformers.__version__, "torch": torch.__version__,
                "loaded": self.model is not None}
