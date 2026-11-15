"""Artifact-digest verification.

The point of these: a number in a published report names a model, and that name has to still mean
the weights it meant when the number was measured. ModelEntry.artifact_hash used to be a field
nothing read, so every one of these cases passed silently before.
"""
import hashlib
import json

import pytest

from modellab_adapters.hf import SNAPSHOT, TransformersAdapter, digest_tree
from modellab_adapters.ollama import BLOBS, MANIFEST, SKIP_BLOB_HASH, OllamaAdapter, blob_digest, split_name
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


def tagged(root) -> str:
    """What the adapter reports: a digest carries the method that produced it."""
    return f"{SNAPSHOT}:{digest_tree(root)}"


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
    entry = hf_entry("hf-pinned", artifact_hash=tagged(root))
    live = TransformersAdapter(entry).artifact_digest()
    assert check_digest(session, entry, live).status == "verified"


def test_weights_edited_under_a_pinned_transformers_model_are_caught(session, tmp_path, monkeypatch):
    root = _snapshot(tmp_path / "snap", {"model.safetensors": b"real weights", "config.json": b"{}"})
    pinned = tagged(root)
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
    assert health["digest"] == tagged(root)


# --- Ollama: hashing the blobs, and not confusing them with the server's own word ------------
# A synthetic store, so these run without Ollama installed and without touching a real one.

INNER = "application/vnd.docker.distribution.manifest.v2+json"


def ollama_store(root, blobs: dict[str, bytes], name="qwen3:8b", served=None):
    """Build a store laid out the way Ollama lays one out, and return the served digest."""
    refs = []
    for media, body in blobs.items():
        name_ = hashlib.sha256(body).hexdigest()
        (root / "blobs").mkdir(parents=True, exist_ok=True)
        (root / "blobs" / f"sha256-{name_}").write_bytes(body)
        refs.append({"mediaType": media, "digest": f"sha256:{name_}"})
    inner = next((r["digest"] for r in refs if r["mediaType"] == INNER), None)
    host, namespace, model, tag = split_name(name)
    path = root / "manifests" / host / namespace / model / tag
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schemaVersion": 2, "layers": refs}))
    return served or (inner.split(":", 1)[1] if inner else None)


def weights_store(root, weights=b"gguf weights", name="qwen3:8b"):
    return ollama_store(root, {"application/vnd.ollama.image.model": weights, INNER: b"canonical manifest"}, name=name)


def test_ollama_blobs_hash_to_a_stable_digest(tmp_path):
    served = weights_store(tmp_path)
    first = blob_digest("qwen3:8b", served, root=tmp_path)
    assert first and len(first) == 64
    assert blob_digest("qwen3:8b", served, root=tmp_path) == first


def test_a_blob_edited_in_place_is_caught_though_its_name_never_changes(tmp_path):
    """The whole point: the filename, the manifest and the server's reported digest all stay put."""
    served = weights_store(tmp_path)
    before = blob_digest("qwen3:8b", served, root=tmp_path)
    blob = next((tmp_path / "blobs").glob("sha256-*"))
    original = blob.read_bytes()
    blob.write_bytes(b"tampered weights, same filename")
    after = blob_digest("qwen3:8b", served, root=tmp_path)
    assert after is not None and after != before
    blob.write_bytes(original)
    assert blob_digest("qwen3:8b", served, root=tmp_path) == before


def test_a_store_that_is_not_the_servers_is_refused(tmp_path):
    """Without the link, a local directory says nothing about which weights the daemon serves."""
    weights_store(tmp_path)
    assert blob_digest("qwen3:8b", "f" * 64, root=tmp_path) is None


def test_an_incomplete_store_is_not_verified(tmp_path):
    served = weights_store(tmp_path)
    next((tmp_path / "blobs").glob("sha256-*")).unlink()
    assert blob_digest("qwen3:8b", served, root=tmp_path) is None


def test_a_model_that_is_not_in_the_store_is_refused(tmp_path):
    served = weights_store(tmp_path)
    assert blob_digest("llama3:70b", served, root=tmp_path) is None


def test_a_namespaced_model_resolves_to_its_own_manifest(tmp_path):
    name = "huihui_ai/qwen3-abliterated:8b-v2"
    served = weights_store(tmp_path, name=name)
    assert split_name(name) == ("registry.ollama.ai", "huihui_ai", "qwen3-abliterated", "8b-v2")
    assert blob_digest(name, served, root=tmp_path) is not None


def test_split_name_defaults_match_ollamas_layout():
    assert split_name("qwen3:8b") == ("registry.ollama.ai", "library", "qwen3", "8b")
    assert split_name("qwen3") == ("registry.ollama.ai", "library", "qwen3", "latest")
    assert split_name("host.example/ns/model:tag") == ("host.example", "ns", "model", "tag")


def test_skipping_the_hash_downgrades_the_claim_rather_than_faking_it(tmp_path, monkeypatch):
    served = weights_store(tmp_path)
    monkeypatch.setenv(SKIP_BLOB_HASH, "1")
    assert blob_digest("qwen3:8b", served, root=tmp_path) is None


def test_a_remote_server_falls_back_to_its_own_manifest_digest(monkeypatch, tmp_path):
    """Hashing this machine's blobs while a remote daemon serves others would be a false pass."""
    monkeypatch.setenv("MODELLAB_ALLOW_REMOTE_INFERENCE", "1")
    served = weights_store(tmp_path)
    monkeypatch.setattr("modellab_adapters.ollama.models_root", lambda: tmp_path)
    remote = OllamaAdapter(entry(backend_model="qwen3:8b"), base_url="http://10.0.0.5:11434")
    monkeypatch.setattr(OllamaAdapter, "manifest_digest", lambda self: served)
    assert remote.local_store() is False
    assert remote.artifact_digest() == f"{MANIFEST}:{served}"


def test_a_loopback_server_reports_the_stronger_kind(monkeypatch, tmp_path):
    served = weights_store(tmp_path)
    monkeypatch.setattr("modellab_adapters.ollama.models_root", lambda: tmp_path)
    monkeypatch.setattr(OllamaAdapter, "manifest_digest", lambda self: served)
    local = OllamaAdapter(entry(backend_model="qwen3:8b"), base_url="http://127.0.0.1:11434")
    digest = local.artifact_digest()
    assert digest.startswith(f"{BLOBS}:")
    assert local.health_check()["digest_kind"] in (BLOBS, None)


# --- A pin that cannot be checked is not a pin ----------------------------------------------


def test_a_pinned_model_whose_backend_reports_nothing_is_refused(session):
    """Pinning a digest asks for a check. A backend that reports none leaves that unanswered."""
    check = check_digest(session, entry(artifact_hash=f"{BLOBS}:{A}"), None)
    assert check.status == "unverifiable" and not check.ok
    with pytest.raises(ProvenanceError, match="cannot be checked"):
        enforce(check)


def test_an_unpinned_model_with_no_digest_still_passes(session):
    """Nothing was promised there, so refusing would only punish backends that cannot answer."""
    assert check_digest(session, entry(), None).status == "unavailable"
    assert check_digest(session, entry(), None).ok


def test_digests_of_different_kinds_are_never_compared(session):
    """A bytes hash and a server's own word measure different things."""
    check = check_digest(session, entry(artifact_hash=f"{BLOBS}:{A}"), f"{MANIFEST}:{A}")
    assert check.status == "unverifiable" and not check.ok
    assert "cannot be compared" in check.detail


def test_a_kind_change_is_not_reported_as_drift(session):
    """Moving to a remote daemon weakens the claim; it is not evidence the weights changed."""
    record(session, "prov-test", REVISION, f"{BLOBS}:{A}")
    session.commit()
    check = check_digest(session, entry(), f"{MANIFEST}:{B}")
    assert check.status == "unpinned" and check.ok


def test_drift_within_a_kind_is_still_caught(session):
    record(session, "prov-test", REVISION, f"{BLOBS}:{A}")
    session.commit()
    check = check_digest(session, entry(), f"{BLOBS}:{B}")
    assert check.status == "drift" and not check.ok
