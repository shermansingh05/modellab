"""Persistence. SQLite for the zero-dependency demo, PostgreSQL for shared use: same schema, same migrations."""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class Base(DeclarativeBase):
    pass


class Model(Base):
    __tablename__ = "models"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    entry: Mapped[dict] = mapped_column(JSON)
    download_status: Mapped[str] = mapped_column(String, default="unknown")
    runtime_status: Mapped[str] = mapped_column(String, default="stopped")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revisions: Mapped[list[ModelRevision]] = relationship(back_populates="model", cascade="all, delete-orphan")


class ModelRevision(Base):
    __tablename__ = "model_revisions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rev"))
    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), index=True)
    revision: Mapped[str | None] = mapped_column(String)
    artifact_hash: Mapped[str | None] = mapped_column(String)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    model: Mapped[Model] = relationship(back_populates="revisions")
    __table_args__ = (UniqueConstraint("model_id", "revision", "artifact_hash"),)


class ScenarioSuite(Base):
    __tablename__ = "scenario_suites"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("suite"))
    manifest_hash: Mapped[str] = mapped_column(String, unique=True)
    scenario_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("sv"))
    suite_id: Mapped[str] = mapped_column(ForeignKey("scenario_suites.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    spec: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("suite_id", "scenario_id"),)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("exp"))
    name: Mapped[str] = mapped_column(String)
    family: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CampaignConfigRow(Base):
    __tablename__ = "campaign_configs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("cfg"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("run"))
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    campaign_config_id: Mapped[str] = mapped_column(ForeignKey("campaign_configs.id"))
    suite_id: Mapped[str | None] = mapped_column(ForeignKey("scenario_suites.id"))
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    total_trials: Mapped[int] = mapped_column(Integer, default=0)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeneratedPayload(Base):
    __tablename__ = "generated_payloads"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("pay"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(String)
    strategy: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)
    valid: Mapped[bool] = mapped_column(Boolean)
    fingerprint: Mapped[str] = mapped_column(String)
    trace_ref: Mapped[str] = mapped_column(String)


class Trial(Base):
    __tablename__ = "trials"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("trial"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    key: Mapped[str] = mapped_column(String)
    scenario_id: Mapped[str] = mapped_column(String, index=True)
    scenario_version: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    request_label: Mapped[str | None] = mapped_column(String)
    model_id: Mapped[str] = mapped_column(String, index=True)
    guardrail_preset: Mapped[str] = mapped_column(String, index=True)
    trial_index: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer)
    payload_id: Mapped[str | None] = mapped_column(ForeignKey("generated_payloads.id"))
    status: Mapped[str] = mapped_column(String, default="running")
    objective_achieved: Mapped[bool | None] = mapped_column(Boolean)
    legit_success: Mapped[bool | None] = mapped_column(Boolean)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    unauthorized_attempts: Mapped[int] = mapped_column(Integer, default=0)
    unauthorized_executions: Mapped[int] = mapped_column(Integer, default=0)
    blocked_attempts: Mapped[int] = mapped_column(Integer, default=0)
    false_positive_denials: Mapped[int] = mapped_column(Integer, default=0)
    guardrail_intervened: Mapped[bool] = mapped_column(Boolean, default=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    answer: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    wall_ms: Mapped[float | None] = mapped_column(Float)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    tokens_per_s: Mapped[float | None] = mapped_column(Float)
    gpu_memory_mb: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("run_id", "key"),)


class InferenceEvent(Base):
    __tablename__ = "inference_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("inf"))
    trial_id: Mapped[str | None] = mapped_column(ForeignKey("trials.id"), index=True)
    model_id: Mapped[str] = mapped_column(String, index=True)
    step: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ToolEventRow(Base):
    __tablename__ = "tool_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("tool"))
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String)
    args: Mapped[dict] = mapped_column(JSON)
    executed: Mapped[bool] = mapped_column(Boolean)
    denied_by: Mapped[str | None] = mapped_column(String)
    ok: Mapped[bool | None] = mapped_column(Boolean)
    result: Mapped[str | None] = mapped_column(Text)


class GuardrailDecisionRow(Base):
    __tablename__ = "guardrail_decisions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("gd"))
    trial_id: Mapped[str] = mapped_column(ForeignKey("trials.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("eval"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    model_id: Mapped[str | None] = mapped_column(String)
    guardrail_preset: Mapped[str | None] = mapped_column(String)
    metrics: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("run_id", "model_id", "guardrail_preset"),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("art"))
    kind: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TrainingJob(Base):
    __tablename__ = "training_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("job"))
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchReport(Base):
    __tablename__ = "research_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("rpt"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    body: Mapped[dict] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def default_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    from modellab_experiments.scenarios import repo_root

    path = repo_root() / "var" / "modellab.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(url: str | None = None):
    url = url or default_url()
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


_factories: dict[str, sessionmaker] = {}


def get_factory(url: str | None = None) -> sessionmaker:
    url = url or default_url()
    if url not in _factories:
        migrate(url)
        _factories[url] = sessionmaker(make_engine(url), expire_on_commit=False)
    return _factories[url]
