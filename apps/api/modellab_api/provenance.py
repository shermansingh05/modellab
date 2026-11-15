"""Artifact-digest verification for the model registry.

A published result attributes a number to a named model. If the weights behind that name change,
every earlier number silently stops describing the thing it claims to describe — and nothing in a
report would show it. `ModelEntry.artifact_hash` existed as a field but was never checked against
anything, so pinning a digest bought a reader no guarantee at all. This module is what makes it
mean something, and what notices when an unpinned model's weights move underneath a run.

Not every backend can answer the question, and the ones that can do not answer it equally well, so
every digest is tagged with how it was arrived at: `snapshot:` and `blobs:` hash the weight bytes
on disk, while `manifest:` only repeats what an Ollama server said about itself. Those are
different claims and comparing them would be meaningless, so a comparison only ever happens
within a kind. vLLM and the mock fixtures expose nothing at all.

Nothing here is a signature chain back to a publisher. It answers a narrower question: are these
the same weights as last time, and the ones the registry named.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from modellab_api.db import ModelRevision
from modellab_schemas import ModelEntry

#: Statuses that let a run proceed. `drift`, `mismatch` and `unverifiable` do not.
#: `unavailable` passes only because nothing was pinned, so no check was ever promised.
PASSING = ("verified", "unpinned", "unavailable")

DRIFT_OVERRIDE = "MODELLAB_ALLOW_DIGEST_DRIFT"


class ProvenanceError(RuntimeError):
    """Raised when a model's live digest contradicts what the registry or the database recorded."""


@dataclass(frozen=True)
class DigestCheck:
    """The outcome of comparing a model's live artifact digest against what is on record."""

    model_id: str
    status: str
    live: str | None = None
    expected: str | None = None
    previous: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status in PASSING

    @property
    def detail(self) -> str:
        if self.status == "verified":
            return f"live digest matches the pinned artifact_hash ({_short(self.live)})"
        if self.status == "mismatch":
            return (f"pinned artifact_hash is {_short(self.expected)} but the backend is serving "
                    f"{_short(self.live)}: these are different weights")
        if self.status == "drift":
            before = ", ".join(_short(d) for d in self.previous)
            return (f"backend is serving {_short(self.live)}, but this model previously ran as {before}: "
                    "the weights changed under a name whose results are already on record")
        if self.status == "unpinned":
            return (f"no artifact_hash pinned; recording {_short(self.live)} as the first digest seen "
                    "(pin it in the config to make this a check)")
        if self.status == "unverifiable" and not self.live:
            return (f"artifact_hash is pinned ({_short(self.expected)}) but this backend reports no digest, "
                    "so the pin cannot be checked at all")
        if self.status == "unverifiable":
            return (f"pinned artifact_hash was produced by {kind_of(self.expected)!r} but the backend reports a "
                    f"{kind_of(self.live)!r} digest: these measure different things and cannot be compared")
        return "this backend reports no artifact digest, and none was pinned, so there is nothing to verify"

    def as_dict(self) -> dict:
        return {"model_id": self.model_id, "status": self.status, "ok": self.ok, "detail": self.detail,
                "live_digest": self.live, "digest_kind": kind_of(self.live), "pinned_digest": self.expected,
                "previous_digests": list(self.previous)}


def kind_of(digest: str | None) -> str | None:
    """How a digest was produced, read off the value itself.

    An untagged digest is treated as its own kind rather than silently matching a tagged one: a
    value recorded before digests carried their method is not known to be comparable with one.
    """
    if not digest:
        return None
    kind, sep, _ = digest.partition(":")
    return kind if sep else "untagged"


def _short(digest: str | None) -> str:
    if not digest:
        return "none"
    kind, sep, body = digest.partition(":")
    if sep and len(body) > 19:
        return f"{kind}:{body[:12]}…"
    return digest if len(digest) <= 24 else f"{digest[:21]}…"


def recorded_digests(session: Session, model_id: str, revision: str | None) -> tuple[str, ...]:
    """Digests already recorded for this model at this revision, oldest first."""
    rows = session.scalars(
        select(ModelRevision)
        .where(ModelRevision.model_id == model_id, ModelRevision.revision == revision,
               ModelRevision.artifact_hash.is_not(None))
        .order_by(ModelRevision.recorded_at)
    ).all()
    return tuple(dict.fromkeys(r.artifact_hash for r in rows))


def check_digest(session: Session, entry: ModelEntry, live: str | None) -> DigestCheck:
    """Compare a backend's live digest against the pinned value, then against what was seen before.

    A pin is authoritative: if the config names a digest, anything else is a mismatch. Without a
    pin this falls back to trust-on-first-use, which is weaker but still catches the case that
    matters most in practice — weights replaced under a name whose results are already published.

    A pin that cannot be checked is a refusal, not a pass. Pinning a digest is a request to verify
    it, so a backend that reports nothing, or that reports a kind of digest the pin cannot be
    compared against, leaves the request unanswered and the run must not proceed on that basis.
    Only comparisons within a kind mean anything, so digests recorded under another kind are not
    evidence of drift: they are simply not evidence either way.
    """
    pin = entry.artifact_hash
    if not live:
        return DigestCheck(entry.id, "unverifiable" if pin else "unavailable", expected=pin)
    if pin:
        if kind_of(pin) != kind_of(live):
            return DigestCheck(entry.id, "unverifiable", live=live, expected=pin)
        status = "verified" if pin == live else "mismatch"
        return DigestCheck(entry.id, status, live=live, expected=pin)
    comparable = [d for d in recorded_digests(session, entry.id, entry.revision) if kind_of(d) == kind_of(live)]
    others = tuple(d for d in comparable if d != live)
    if others:
        return DigestCheck(entry.id, "drift", live=live, previous=others)
    return DigestCheck(entry.id, "unpinned", live=live)


def drift_allowed() -> bool:
    """Drift is a refusal by default. Re-pulling a model legitimately is what this escape hatch is for."""
    return os.environ.get(DRIFT_OVERRIDE) == "1"


def enforce(check: DigestCheck) -> None:
    """Fail a run closed rather than publish numbers attributed to weights we cannot account for."""
    if check.ok:
        return
    if check.status == "drift" and drift_allowed():
        return
    hint = f" Set {DRIFT_OVERRIDE}=1 to accept the new digest." if check.status == "drift" else ""
    raise ProvenanceError(f"{check.model_id}: {check.detail}.{hint}")


def record(session: Session, model_id: str, revision: str | None, digest: str | None) -> None:
    """Record a digest the first time it is seen, so drift has something to compare against."""
    if not digest:
        return
    seen = session.scalar(select(ModelRevision).where(
        ModelRevision.model_id == model_id, ModelRevision.artifact_hash == digest))
    if seen is None:
        session.add(ModelRevision(model_id=model_id, revision=revision, artifact_hash=digest))


def verify_model(session: Session, entry: ModelEntry) -> DigestCheck:
    """Health-check a model, compare its digest, and record it. Used by the API and the CLI alike."""
    from modellab_adapters import get_adapter

    health = get_adapter(entry).health_check()
    check = check_digest(session, entry, health.get("digest"))
    if check.status in ("verified", "unpinned"):
        record(session, entry.id, entry.revision, check.live)
        session.commit()
    return check
