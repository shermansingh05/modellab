"""Typed contracts shared by every ModelLab service."""
from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class Variant(StrEnum):
    standard = "standard"
    abliterated = "abliterated"
    fixture = "fixture"


class Backend(StrEnum):
    mock = "mock"
    ollama = "ollama"
    transformers = "transformers"
    vllm = "vllm"


class ModelEntry(BaseModel):
    """A registry entry. Remote code stays disabled, and real weights must pin a reviewed revision."""

    model_config = ConfigDict(protected_namespaces=())

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    display_name: str
    hf_repo: str | None = None
    revision: str | None = None
    base_model: str | None = None
    family: str
    parameter_count: int | None = None
    license: str | None = None
    purpose: str = "research"
    variant: Variant = Variant.standard
    quantization: str = "unknown"
    backend: Backend
    backend_model: str | None = Field(default=None, description="Backend-specific name, such as an Ollama tag.")
    artifact_hash: str | None = None
    chat_template_id: str = "backend-default"
    context_window: int = 8192
    hardware_requirements: dict[str, Any] = {}
    trust: dict[str, Any] = {}
    trust_remote_code: Literal[False] = False

    @model_validator(mode="after")
    def _check_pinning(self) -> ModelEntry:
        if self.backend == Backend.transformers:
            if not self.hf_repo or not self.revision or not SHA_RE.match(self.revision):
                raise ValueError("transformers models must pin hf_repo and a 40-character commit revision")
        if self.revision and not SHA_RE.match(self.revision):
            raise ValueError("revision must be a 40-character commit hash")
        if self.backend in (Backend.ollama, Backend.vllm) and not self.backend_model:
            raise ValueError(f"{self.backend} models must set backend_model")
        return self


class GenerationConfig(BaseModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    max_tokens: int = Field(default=512, gt=0, le=8192)
    seed: int | None = 0
    thinking: bool = False
    timeout_s: float = Field(default=180.0, gt=0)


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class InferenceResult(BaseModel):
    text: str = ""
    model_id: str
    backend: str
    backend_version: str | None = None
    revision: str | None = None
    quantization: str | None = None
    hardware: str | None = None
    template_version: str | None = None
    config: GenerationConfig
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    wall_ms: float = 0.0
    ttft_ms: float | None = None
    tokens_per_s: float | None = None
    peak_rss_mb: float | None = None
    gpu_memory_mb: float | None = None
    error: str | None = None


class ToolRule(BaseModel):
    tool: str
    args_match: dict[str, str] = Field(default_factory=dict, description="fnmatch patterns for string arguments.")


class Predicate(BaseModel):
    type: Literal[
        "tool_executed", "tool_requested", "tool_denied", "answer_contains", "answer_not_contains", "refused",
        "not_refused",
    ]
    tool: str | None = None
    args_contains: dict[str, str] = Field(default_factory=dict)
    text: str | None = None


class Budgets(BaseModel):
    max_steps: int = Field(default=6, gt=0, le=25)
    max_tool_calls: int = Field(default=8, gt=0, le=50)
    wall_seconds: float = Field(default=300.0, gt=0)
    max_tokens_per_step: int = Field(default=400, gt=0)


class ScenarioKind(StrEnum):
    attack = "attack"
    benign = "benign"
    refusal = "refusal"


class AttackSurface(StrEnum):
    none = "none"
    user_prompt = "user_prompt"
    document = "document"
    repository = "repository"
    tool_response = "tool_response"
    mcp_metadata = "mcp_metadata"
    mcp_response = "mcp_response"
    conversation = "conversation"


class Scenario(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str
    family: Literal["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    category: str
    kind: ScenarioKind
    request_label: Literal["harmless", "ambiguous", "disallowed"] | None = None
    task: str
    followups: list[str] = Field(default_factory=list, description="Later user turns.")
    protected_boundary: str
    attacker_surface: AttackSurface = AttackSurface.none
    payload: str | None = None
    payload_target: str | None = Field(default=None, description="Document ID, repo path, channel, or MCP tool.")
    authorized: list[ToolRule] = Field(default_factory=list)
    prohibited: list[ToolRule] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    principal: dict[str, str] = Field(default_factory=lambda: {"user": "analyst", "tenant": "acme"})
    expected_safe_behavior: str
    attacker_objective: str | None = None
    objective_criteria: list[Predicate] = Field(default_factory=list)
    utility_criteria: list[Predicate] = Field(default_factory=list)
    budgets: Budgets = Budgets()

    @model_validator(mode="after")
    def _check_kind(self) -> Scenario:
        if self.kind == ScenarioKind.attack and not (self.objective_criteria and self.attacker_objective):
            raise ValueError("attack scenarios need attacker_objective and deterministic objective_criteria")
        if self.kind == ScenarioKind.attack and self.attacker_surface == AttackSurface.none:
            raise ValueError("attack scenarios must declare an attacker-controlled surface")
        if self.kind == ScenarioKind.refusal and not self.request_label:
            raise ValueError("refusal scenarios need request_label")
        if self.kind == ScenarioKind.benign and self.payload:
            raise ValueError("benign controls cannot carry a payload")
        return self

    @field_validator("version")
    @classmethod
    def _v(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+$", v):
            raise ValueError("version must look like 1.0")
        return v


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Decision(StrEnum):
    allow = "allow"
    flag = "flag"
    deny = "deny"
    require_approval = "require_approval"


class GuardrailDecision(BaseModel):
    guardrail: str
    stage: Literal["input", "retrieved", "tool", "output"]
    decision: Decision
    reason_code: str
    deterministic: bool = False
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    version: str = "1"


class ToolEvent(BaseModel):
    seq: int
    tool: str
    args: dict[str, Any]
    requested: bool = True
    executed: bool = False
    denied_by: str | None = None
    ok: bool | None = None
    result: str | None = None
    error: str | None = None


class CampaignConfig(BaseModel):
    """Everything needed to rebuild a run's trial matrix."""

    model_config = ConfigDict(protected_namespaces=())

    name: str
    family: str | None = None
    scenarios: list[str] = Field(default_factory=list, description="Scenario IDs. Empty means all in selected kinds.")
    kinds: list[ScenarioKind] = Field(default_factory=lambda: list(ScenarioKind))
    defenders: list[str] = Field(min_length=1)
    guardrails: list[str] = Field(default_factory=lambda: ["none"])
    trials: int = Field(default=1, gt=0, le=100)
    generation: GenerationConfig = GenerationConfig()
    attacker: str | None = Field(default=None, description="Registered model ID that generates payloads.")
    attack_strategy: Literal["scenario", "template", "paraphrase", "multilingual", "model"] = "scenario"
    attack_budget: int = Field(default=3, gt=0, le=50)
    base_seed: int = 0
