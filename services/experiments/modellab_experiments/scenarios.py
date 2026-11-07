"""Scenario manifests: versioned YAML in the repository."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

from modellab_schemas import ModelEntry, Scenario


def repo_root() -> Path:
    if env := os.environ.get("MODELLAB_ROOT"):
        return Path(env)
    here = Path(__file__).resolve()
    for parent in [Path.cwd(), *here.parents]:
        if (parent / "scenarios").is_dir() and (parent / "configs").is_dir():
            return parent
    raise RuntimeError("cannot find the ModelLab repository root; set MODELLAB_ROOT")


@lru_cache
def load_scenarios() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for path in sorted((repo_root() / "scenarios").rglob("*.yaml")):
        scenario = Scenario.model_validate(yaml.safe_load(path.read_text()))
        if scenario.id in out:
            raise ValueError(f"duplicate scenario id {scenario.id}")
        out[scenario.id] = scenario
    return out


def manifest_hash() -> str:
    spec = {k: v.model_dump(mode="json") for k, v in sorted(load_scenarios().items())}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def load_model_configs() -> list[ModelEntry]:
    return [ModelEntry.model_validate(yaml.safe_load(p.read_text()))
            for p in sorted((repo_root() / "configs" / "models").glob("*.yaml"))]
