"""Hugging Face Transformers. Needs the `ml` extra. Remote code is never trusted, and revisions are pinned."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from modellab_adapters.base import ModelAdapter
from modellab_schemas import GenerationConfig, InferenceResult, Message

SAFE_PATTERNS = ["*.safetensors", "*.json", "*.txt", "tokenizer.model", "*.jinja"]

#: Read in chunks so a multi-gigabyte shard never has to fit in memory.
_CHUNK = 1024 * 1024

#: This digest is a hash of the snapshot's bytes. The kind travels with the value so it is never
#: compared against a digest that was arrived at some other way.
SNAPSHOT = "snapshot"


def download(repo: str, revision: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, revision=revision, allow_patterns=SAFE_PATTERNS)


def snapshot_path(repo: str, revision: str) -> str | None:
    """Where a pinned revision already lives on disk, or None.

    Resolution is local-only on purpose. A health check must never be the thing that starts a
    multi-gigabyte download, and a digest computed from weights fetched during the check would
    verify nothing: it would only confirm that what was just downloaded hashes to itself.
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return None
    try:
        return snapshot_download(repo, revision=revision, allow_patterns=SAFE_PATTERNS, local_files_only=True)
    except Exception:
        return None


def digest_tree(root: str | Path) -> str | None:
    """A content digest over every file in a model snapshot.

    This hashes the bytes the adapter will actually load, not a name a server hands back, so it
    catches a weight file edited in place as readily as a re-pull. Paths are included alongside
    the per-file hashes, so moving a shard or dropping a tokenizer changes the result too, and
    they are sorted so the digest does not depend on directory order.
    """
    base = Path(root)
    if not base.is_dir():
        return None
    files = sorted(p for p in base.rglob("*") if p.is_file())
    if not files:
        return None
    tree = hashlib.sha256()
    for path in files:
        inner = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                inner.update(chunk)
        tree.update(f"{path.relative_to(base).as_posix()}:{inner.hexdigest()}\n".encode())
    return tree.hexdigest()


class TransformersAdapter(ModelAdapter):
    def __init__(self, entry):
        super().__init__(entry)
        self.model = None
        self.tokenizer = None
        self.device = None
        self._digest: str | None = None

    def load_model(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(self.entry.hf_repo, revision=self.entry.revision, trust_remote_code=False)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.entry.hf_repo, revision=self.entry.revision, trust_remote_code=False, use_safetensors=True, torch_dtype="auto"
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
        kw = {"max_new_tokens": config.max_tokens, "pad_token_id": self.tokenizer.eos_token_id}
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
            except Exception as exc:
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

    def artifact_digest(self) -> str | None:
        """The digest of the cached snapshot, computed once per adapter.

        Hashing real weights costs real I/O, so the result is memoized: a run health-checks a
        model once, and `modellab models verify` builds one adapter per model.
        """
        if self._digest is None:
            # The schema already refuses a transformers entry without a repo and a pinned commit.
            path = snapshot_path(self.entry.hf_repo, self.entry.revision)
            tree = digest_tree(path) if path else None
            self._digest = f"{SNAPSHOT}:{tree}" if tree else None
        return self._digest

    def health_check(self) -> dict:
        digest = self.artifact_digest()
        try:
            import torch
            import transformers
        except ImportError:
            # Verification does not need to run the model, so report the digest either way.
            return {"ok": False, "backend": "transformers", "digest": digest,
                    "detail": "install the ml extra: uv sync --extra ml"}
        return {"ok": True, "backend": "transformers", "version": transformers.__version__, "torch": torch.__version__,
                "digest": digest, "digest_kind": SNAPSHOT if digest else None, "loaded": self.model is not None}
