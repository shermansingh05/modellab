"""Ollama over its local HTTP API. Refuses non-loopback hosts unless explicitly allowed."""
from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import httpx

from modellab_adapters.base import ModelAdapter
from modellab_schemas import GenerationConfig, InferenceResult, Message, ModelEntry

LOOPBACK = {"localhost", "127.0.0.1", "::1"}

#: How a digest was arrived at. A value carries its own kind so the two can never be compared by
#: accident: `blobs` is a hash of the weight bytes on disk, `manifest` only repeats what the server
#: said. Treating one as the other would either forge a verification or raise a false alarm.
BLOBS = "blobs"
MANIFEST = "manifest"

_CHUNK = 1024 * 1024


def models_root() -> Path:
    """Where Ollama keeps manifests and blobs."""
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def split_name(name: str) -> tuple[str, str, str, str]:
    """Split an Ollama model name into the path segments its manifest is stored under."""
    host, namespace, tag = "registry.ollama.ai", "library", "latest"
    path, _, maybe_tag = name.partition(":")
    if maybe_tag:
        tag = maybe_tag
    parts = path.split("/")
    if len(parts) == 3:
        host, namespace, model = parts
    elif len(parts) == 2:
        namespace, model = parts
    else:
        model = parts[0]
    return host, namespace, model, tag


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _bare(digest: str | None) -> str | None:
    """Ollama has reported digests both bare and `sha256:`-prefixed. Compare them one way."""
    if not digest:
        return None
    return digest.split(":", 1)[1] if digest.startswith("sha256:") else digest


#: Ollama's manifest carries the canonical registry manifest as a layer of its own, and the digest
#: `/api/tags` reports for a model is that layer's digest. Finding it there is what ties the store
#: on disk to the server that is answering.
INNER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"

#: Hashing a multi-gigabyte model blob costs real I/O. This downgrades the claim to the server's
#: own manifest digest rather than silently skipping a check that was asked for.
SKIP_BLOB_HASH = "MODELLAB_SKIP_BLOB_HASH"


def blob_digest(model_name: str, served_manifest_digest: str, root: Path | None = None) -> str | None:
    """Hash the weight bytes Ollama has on disk, or None when they cannot be accounted for.

    Ollama names each blob after the SHA-256 of its contents, so re-hashing the bytes and folding
    the real hashes together catches a blob edited in place — the filename, the manifest and the
    server's own reported digest all stay the same in that case.

    This only speaks for the running server if the store on disk is the store that server is
    using, and a local directory proves nothing about a remote daemon. The link is the digest
    `/api/tags` reports: it appears in the local manifest as the INNER_MANIFEST layer, so finding
    it there identifies this store as the one the server answered about. That was checked against
    a live Ollama for both a library and a namespaced model, and it is still enforced at runtime
    rather than assumed: if the link is absent this returns None and the caller falls back to the
    manifest digest. A changed packaging format therefore costs a weaker answer, never a false
    verification.
    """
    if os.environ.get(SKIP_BLOB_HASH) == "1":
        return None
    base = root or models_root()
    host, namespace, model, tag = split_name(model_name)
    path = base / "manifests" / host / namespace / model / tag
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    refs = [manifest.get("config") or {}, *(manifest.get("layers") or [])]
    served = _bare(served_manifest_digest)
    if not any(ref.get("mediaType") == INNER_MANIFEST and _bare(ref.get("digest")) == served for ref in refs):
        return None
    names = sorted({_bare(ref.get("digest")) for ref in refs if ref.get("digest")})
    tree = hashlib.sha256()
    for name in names:
        blob = base / "blobs" / f"sha256-{name}"
        if not blob.is_file():
            return None  # An incomplete store is not something to publish a verification about.
        tree.update(f"{name}:{_sha256_file(blob)}\n".encode())
    return tree.hexdigest()


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
        self._digest: str | None = None

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

    def manifest_digest(self) -> str | None:
        """The digest the server reports for this model. Its own word, not an independent check."""
        try:
            for m in self._client.get("/api/tags", timeout=5).json().get("models", []):
                if m.get("name") == self.entry.backend_model:
                    return _bare(m.get("digest"))
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def local_store(self) -> bool:
        """Whether the blobs on this machine can be the ones the server is serving."""
        return urlparse(self.base_url).hostname in LOOPBACK

    def artifact_digest(self) -> str | None:
        """A kind-tagged digest, strongest first. Memoized: hashing real weights costs real I/O."""
        if self._digest is None:
            served = self.manifest_digest()
            if served is None:
                return None
            local = blob_digest(self.entry.backend_model, served) if self.local_store() else None
            self._digest = f"{BLOBS}:{local}" if local else f"{MANIFEST}:{served}"
        return self._digest

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
        return {"ok": True, "backend": "ollama", "version": version, "digest": digest,
                "digest_kind": digest.split(":", 1)[0]}
