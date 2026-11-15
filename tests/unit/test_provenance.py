"""Artifact-digest verification.

The point of these: a number in a published report names a model, and that name has to still mean
the weights it meant when the number was measured. ModelEntry.artifact_hash used to be a field
nothing read, so every one of these cases passed silently before.
"""
import pytest

from modellab_adapters.hf import TransformersAdapter, digest_tree
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


# --- The transformers backend's own digest -------------------------------------------------
# These exercise digest_tree directly, because it is a pure function over a directory: the tests
# run without torch, transformers or huggingface_hub installed, which is also how CI runs them.


def hf_entry(model_id: str, **kw) -> ModelEntry:
    return entry(id=model_id, backend="transformers", backend_model=None,
                 hf_repo="org/model", revision="a" * 40, **kw)


def _snapshot(root, files: dict[str, bytes]):
    for name, blob in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    return root


def test_the_same_weights_hash_the_same_way(tmp_path):
    one = _snapshot(tmp_path / "a", {"model.safetensors": b"weights", "config.json": b"{}"})
    two = _snapshot(tmp_path / "b", {"config.json": b"{}", "model.safetensors": b"weights"})
    assert digest_tree(one) == digest_tree(two)
    assert len(digest_tree(one)) == 64


def test_a_weight_file_edited_in_place_changes_the_digest(tmp_path):
    root = _snapshot(tmp_path / "s", {"model.safetensors": b"weights", "config.json": b"{}"})
    before = digest_tree(root)
    (root / "model.safetensors").write_bytes(b"weightt")
    assert digest_tree(root) != before


def test_renaming_a_shard_changes_the_digest(tmp_path):
    root = _snapshot(tmp_path / "s", {"model-00001.safetensors": b"w", "config.json": b"{}"})
    before = digest_tree(root)
    (root / "model-00001.safetensors").rename(root / "model-00002.safetensors")
    assert digest_tree(root) != before


def test_a_dropped_tokenizer_changes_the_digest(tmp_path):
    root = _snapshot(tmp_path / "s", {"model.safetensors": b"w", "tokenizer.json": b"{}"})
    before = digest_tree(root)
    (root / "tokenizer.json").unlink()
    assert digest_tree(root) != before


def test_nothing_cached_means_no_digest_rather_than_a_fake_one(tmp_path):
    assert digest_tree(tmp_path / "never-downloaded") is None
    assert digest_tree(_snapshot(tmp_path / "empty", {})) is None


def test_an_uncached_model_reports_unavailable_not_verified(session):
    entry = hf_entry("hf-uncached")
    adapter = TransformersAdapter(entry)
    assert adapter.artifact_digest() is None
    assert check_digest(session, entry, adapter.artifact_digest()).status == "unavailable"


def test_a_cached_snapshot_is_verified_against_its_pin(session, tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "snap", {"model.safetensors": b"real weights", "config.json": b"{}"})
    monkeypatch.setattr("modellab_adapters.hf.snapshot_path", lambda repo, revision: str(root))
    entry = hf_entry("hf-pinned", artifact_hash=digest_tree(root))
    live = TransformersAdapter(entry).artifact_digest()
    assert check_digest(session, entry, live).status == "verified"


def test_weights_edited_under_a_pinned_transformers_model_are_caught(session, tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "snap", {"model.safetensors": b"real weights", "config.json": b"{}"})
    pinned = digest_tree(root)
    (root / "model.safetensors").write_bytes(b"tampered!!!!")
    monkeypatch.setattr("modellab_adapters.hf.snapshot_path", lambda repo, revision: str(root))
    entry = hf_entry("hf-tampered", artifact_hash=pinned)
    check = check_digest(session, entry, TransformersAdapter(entry).artifact_digest())
    assert check.status == "mismatch" and not check.ok
    with pytest.raises(ProvenanceError, match="different weights"):
        enforce(check)


def test_the_digest_is_computed_once_per_adapter(tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "snap", {"model.safetensors": b"w"})
    calls: list[str] = []

    def once(repo, revision):
        calls.append(repo)
        return str(root)

    monkeypatch.setattr("modellab_adapters.hf.snapshot_path", once)
    entry = hf_entry("hf-memo")
    adapter = TransformersAdapter(entry)
    assert adapter.artifact_digest() == adapter.artifact_digest()
    assert len(calls) == 1


def test_health_reports_the_digest_even_without_the_ml_extra(tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "snap", {"model.safetensors": b"w"})
    monkeypatch.setattr("modellab_adapters.hf.snapshot_path", lambda repo, revision: str(root))
    entry = hf_entry("hf-health")
    health = TransformersAdapter(entry).health_check()
    # Whether torch is installed decides `ok`, never whether the weights can be accounted for.
    assert health["digest"] == digest_tree(root)
