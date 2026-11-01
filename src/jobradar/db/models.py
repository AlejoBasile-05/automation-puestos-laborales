"""Modelos de base de datos SQLAlchemy 2.x."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarativa para modelos SQLAlchemy."""
    pass


class JobStatus(StrEnum):
    """Estados válidos de una vacante."""
    NEW = "new"
    REVIEWED = "reviewed"
    PREPARED = "prepared"
    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    DISCARDED = "discarded"


class WorkplaceType(StrEnum):
    """Tipos de modalidad de trabajo."""
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class Company(Base):
    """Empresa origen de vacantes."""
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # greenhouse, lever, workday
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relaciones
    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="company", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "slug", name="uq_company_source_slug"),
    )


class Job(Base):
    """Vacante normalizada."""
    __tablename__ = "jobs"

    # Permite atributos Python no mapeados (por ejemplo ``is_new``).
    __allow_unmapped__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    workplace_type: Mapped[WorkplaceType | None] = mapped_column(Enum(WorkplaceType), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description_text: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    is_open: Mapped[bool] = mapped_column(Integer, nullable=False, default=1)  # SQLite usa 0/1 para Boolean
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.NEW)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Marca calculada en la capa de consultas: no se persiste.
    is_new: bool = False

    # Relaciones
    company: Mapped["Company"] = relationship("Company", back_populates="jobs")
    scores: Mapped[list["Score"]] = relationship("Score", back_populates="job", cascade="all, delete-orphan")
    requirements: Mapped[list["JobRequirement"]] = relationship("JobRequirement", back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship("Application", back_populates="job", cascade="all, delete-orphan")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
        Index("ix_job_company_id", "company_id"),
        Index("ix_job_status", "status"),
        Index("ix_job_is_open", "is_open"),
        Index("ix_job_posted_at", "posted_at"),
    )


class Score(Base):
    """Puntuación de compatibilidad de una vacante contra el CV."""
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    cv_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256 del CV maestro
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)  # aplicar, quizá, descartar
    matches_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    gaps_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    red_flags_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    # Relaciones
    job: Mapped["Job"] = relationship("Job", back_populates="scores")

    __table_args__ = (
        UniqueConstraint("job_id", "cv_hash", "prompt_version", name="uq_score_job_cv_prompt"),
        Index("ix_score_job_id", "job_id"),
    )


class JobRequirement(Base):
    """Requisitos extraídos de una vacante (keywords y knockouts)."""
    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256 de la descripción
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    keywords_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    knockouts_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    # Relaciones
    job: Mapped["Job"] = relationship("Job", back_populates="requirements")

    __table_args__ = (
        UniqueConstraint("job_id", "description_hash", "prompt_version", name="uq_req_job_desc_prompt"),
        Index("ix_job_requirement_job_id", "job_id"),
    )


class Application(Base):
    """Postulación preparada para una vacante."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    tailored_cv_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    docx_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)  # es, en
    required_coverage: Mapped[float] = mapped_column(Float, nullable=False)
    ats_report_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relaciones
    job: Mapped["Job"] = relationship("Job", back_populates="applications")

    __table_args__ = (
        Index("ix_application_job_id", "job_id"),
    )


class Event(Base):
    """Evento/historial de cambios de una vacante."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # status_change, score_computed, etc.
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    # Relaciones
    job: Mapped["Job"] = relationship("Job", back_populates="events")

    __table_args__ = (
        Index("ix_event_job_id", "job_id"),
        Index("ix_event_type", "type"),
        Index("ix_event_created_at", "created_at"),
    )
