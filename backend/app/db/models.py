from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    modality: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    signal_name: Mapped[str | None] = mapped_column(String)
    signal_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String)
    trace_or_session_id: Mapped[str | None] = mapped_column(String, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="accepted")

    __table_args__ = (
        CheckConstraint("severity >= 0 AND severity <= 1", name="ck_events_severity"),
        UniqueConstraint("source", "source_record_id", name="uq_events_source_record"),
        Index("ix_events_entity_timestamp", "entity_id", "timestamp"),
        Index("ix_events_modality_timestamp", "modality", "timestamp"),
    )


class QuarantinedEvent(Base):
    __tablename__ = "quarantined_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    raw_payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class CollapsedEventGroup(Base):
    __tablename__ = "collapsed_event_groups"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    representative_event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    detector_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    context_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    can_open_incident: Mapped[bool] = mapped_column(Boolean, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 1", name="ck_anomalies_score"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_anomalies_threshold"),
    )


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    service: Mapped[str] = mapped_column(String, nullable=False, index=True)
    criticality: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


class TopologyEdge(Base):
    __tablename__ = "topology_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    relationship: Mapped[str] = mapped_column(String, nullable=False)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("source_entity_id <> target_entity_id", name="ck_topology_no_self_edge"),
        UniqueConstraint(
            "source_entity_id", "target_entity_id", "relation_type", name="uq_topology_typed_edge"
        ),
        Index("ix_topology_source_relation", "source_entity_id", "relation_type"),
        Index("ix_topology_target_relation", "target_entity_id", "relation_type"),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    primary_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False, index=True)
    affected_entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    anomaly_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_analysis_run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id"))
    top_hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"))
    confirmed_hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"))

    __table_args__ = (
        CheckConstraint("severity >= 0 AND severity <= 1", name="ck_incidents_severity"),
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    attachment_score: Mapped[float] = mapped_column(Float, nullable=False)
    attachment_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class IncidentEventEvaluation(Base):
    __tablename__ = "incident_event_evaluations"

    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    attachment_score: Mapped[float] = mapped_column(Float, nullable=False)
    attachment_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        CheckConstraint("decision IN ('attached','excluded')", name="ck_event_eval_decision"),
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("incident_id", "revision", name="uq_analysis_incident_revision"),
        Index("ix_analysis_incident_status", "incident_id", "status"),
        Index("ix_analysis_incident_fingerprint", "incident_id", "input_fingerprint"),
        Index(
            "uq_analysis_current_per_incident",
            "incident_id",
            unique=True,
            sqlite_where=text("status = 'current'"),
        ),
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    candidate_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    factor_scores: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "rank", name="uq_hypothesis_run_rank"),
        CheckConstraint("evidence_score >= 0 AND evidence_score <= 100", name="ck_hypothesis_score"),
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"))
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    relevance: Mapped[float] = mapped_column(Float, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("relevance >= 0 AND relevance <= 1", name="ck_evidence_relevance"),
        CheckConstraint(
            "(kind = 'missing' AND source_event_id IS NULL) OR "
            "(kind <> 'missing' AND source_event_id IS NOT NULL)",
            name="ck_evidence_missing_source",
        ),
        Index("ix_evidence_hypothesis_kind", "hypothesis_id", "kind"),
    )


class PlaybookRecommendation(Base):
    __tablename__ = "playbook_recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False, index=True)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class Explanation(Base):
    __tablename__ = "explanations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False, index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    generator: Mapped[str] = mapped_column(String, nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_explanations_incident_created", "incident_id", "created_at"),)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(ForeignKey("hypotheses.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    client_action_id: Mapped[str] = mapped_column(String, nullable=False)
    requested_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"))
    reviewer: Mapped[str] = mapped_column(String, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("incident_id", "client_action_id", name="uq_review_client_action"),
        Index("ix_reviews_incident_created", "incident_id", "created_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_id: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_audit_object", "object_type", "object_id"),)


class HistoricalIncident(Base):
    __tablename__ = "historical_incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    confirmed_cause: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    feature_vector: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

