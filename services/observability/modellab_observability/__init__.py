"""Redaction and tracing helpers. Traces never store raw credentials."""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from opentelemetry import trace

tracer = trace.get_tracer("modellab")

_PATTERNS = [
    (re.compile(r"SYNTH-[A-Z0-9-]+"), "[REDACTED:synthetic-credential]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED:github-token]"),
    (re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"), "[REDACTED:hf-token]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED:api-key]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "[REDACTED:private-key]"),
]


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    return value


def withhold(text: str, label: str | None) -> str:
    """Replies to disallowed requests are kept as a hash unless a researcher opts in."""
    if label == "disallowed" and os.environ.get("MODELLAB_STORE_DISALLOWED_OUTPUT") != "1":
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        return f"[withheld: disallowed-category output, {len(text)} chars, sha256:{digest}]"
    return redact(text) or ""


def configure_tracing(service: str = "modellab") -> None:
    """Exports only when an OTLP endpoint is set. There is no default remote endpoint."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    trace.set_tracer_provider(TracerProvider(resource=Resource.create({"service.name": service})))
