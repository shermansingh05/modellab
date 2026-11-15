"""Artifact-digest verification.

The point of these: a number in a published report names a model, and that name has to still mean
the weights it meant when the number was measured. ModelEntry.artifact_hash used to be a field
nothing read, so every one of these cases passed silently before.
"""
import pytest

from modellab_api.db import Model, ModelRevision
from modellab_api.provenance import DRIFT_OVERRIDE, ProvenanceError, check_digest, enforce, record, recorded_digests
from modellab_schemas import ModelEntry

A = "a" * 64
B = "b" * 64
REVISION = "0" * 40


def entry(**kw) -> ModelEntry:
    base = {"id": "prov-test", "display_name": "Provenance test", "family": "llama",
            "backend": "ollama", "backend_model": "prov:8b", "revision": REVISION}
    return ModelEntry.model_validate({**base, **kw})


@pytest.fixture
def session(factory):
    with factory() as s:
        e = entry()
        if s.get(Model, e.id) is None:
            s.add(Model(id=e.id, entry=e.model_dump(mode="json")))
            s.commit()
        yield s
        s.query(ModelRevision).filter(ModelRevision.model_id == e.id).delete()
        s.commit()


def test_a_pinned_digest_that_matches_is_verified(session):
    check = check_digest(session, entry(artifact_hash=A), A)
    assert (check.status, check.ok) == ("verified", True)
    enforce(check)


def test_a_pinned_digest_that_differs_is_a_mismatch_and_blocks(session):
    """The whole point of the pin: serving other weights under this name must stop the run."""
    check = check_digest(session, entry(artifact_hash=A), B)
    assert (check.status, check.ok) == ("mismatch", False)
    with pytest.raises(ProvenanceError, match="different weights"):
        enforce(check)


def test_a_backend_with_no_digest_says_so_instead_of_claiming_verification(session):
    """vLLM, transformers and the mock fixtures report no digest. Silence is not a pass."""
    check = check_digest(session, entry(), None)
    assert check.status == "unavailable" and check.ok
    assert "nothing to verify" in check.detail


def test_first_digest_seen_is_recorded_not_rejected(session):
    check = check_digest(session, entry(), A)
    assert (check.status, check.ok) == ("unpinned", True)
    record(session, "prov-test", REVISION, A)
    session.commit()
    assert recorded_digests(session, "prov-test", REVISION) == (A,)


def test_weights_changing_under_an_unpinned_model_is_drift_and_blocks(session):
    """Trust-on-first-use: nobody pinned anything, but this model already ran as digest A."""
    record(session, "prov-test", REVISION, A)
    session.commit()
    check = check_digest(session, entry(), B)
    assert (check.status, check.ok) == ("drift", False)
    assert "already on record" in check.detail
    with pytest.raises(ProvenanceError, match=DRIFT_OVERRIDE):
        enforce(check)


def test_drift_can_be_accepted_deliberately(session, monkeypatch):
    """Re-pulling a model on purpose is legitimate, so the refusal has a documented escape hatch."""
    record(session, "prov-test", REVISION, A)
    session.commit()
    check = check_digest(session, entry(), B)
    monkeypatch.setenv(DRIFT_OVERRIDE, "1")
    enforce(check)  # Does not raise.


def test_a_pin_outranks_the_recorded_history(session):
    """A mismatch stays a mismatch even if the wrong digest was recorded earlier."""
    record(session, "prov-test", REVISION, B)
    session.commit()
    assert check_digest(session, entry(artifact_hash=A), B).status == "mismatch"


def test_digests_are_compared_within_a_revision_not_across_them(session):
    """Two revisions legitimately have different weights; that is not drift."""
    record(session, "prov-test", "1" * 40, A)
    session.commit()
    assert check_digest(session, entry(), B).status == "unpinned"
    assert recorded_digests(session, "prov-test", REVISION) == ()


def test_a_failing_check_never_writes_itself_into_the_history(session):
    """Otherwise a mismatch would become the new baseline and the next run would look clean."""
    record(session, "prov-test", REVISION, A)
    session.commit()
    check = check_digest(session, entry(), B)
    assert check.status == "drift"
    assert recorded_digests(session, "prov-test", REVISION) == (A,)
