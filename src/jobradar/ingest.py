"""Orquesta la ingesta de vacantes desde todas las fuentes."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from jobradar.config import CompanyConfig
from jobradar.db.models import Company, Job, JobStatus, WorkplaceType
from jobradar.db.session import get_engine, get_session_factory
from jobradar.sources import get_source
from jobradar.sources.base import JobSource, NormalizedJob

logger = logging.getLogger(__name__)


@dataclass
class IngestError:
    """Error durante la ingesta de una empresa."""
    company_name: str
    source: str
    error_message: str


@dataclass
class IngestSummary:
    """Resumen del resultado de la ingesta."""
    companies_processed: int = 0
    jobs_new: int = 0
    jobs_updated: int = 0
    jobs_closed: int = 0
    errors: list[IngestError] = field(default_factory=list)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def total_jobs(self) -> int:
        return self.jobs_new + self.jobs_updated


def _as_workplace_type(value: str | None) -> WorkplaceType | None:
    """Convierte el valor normalizado al enum, ignorando valores desconocidos."""
    if not value:
        return None
    try:
        return WorkplaceType(value)
    except ValueError:
        return None


def ingest_companies(
    companies: list[CompanyConfig],
    session_factory: Callable[[], Session] | sessionmaker[Session] | None = None,
) -> IngestSummary:
    """Ingesta vacantes de todas las empresas configuradas.

    Args:
        companies: Lista de configuraciones de empresas a procesar.
        session_factory: Fábrica de sesiones opcional (para testing). Si no se provee, usa la default.

    Returns:
        IngestSummary con el resultado de la ingesta.
    """
    if session_factory is None:
        engine = get_engine()
        session_factory = get_session_factory(engine)
    summary = IngestSummary()
    now = datetime.utcnow()

    for company in companies:
        try:
            source: JobSource = get_source(company.source)
            company_config = company.model_dump()
            jobs: list[NormalizedJob] = source.fetch_jobs(company_config)

            with session_factory() as session:
                # Asegurar que la empresa existe en la BD
                company_db = _get_or_create_company(session, company)
                company_db.last_synced_at = now

                # Obtener jobs existentes de esta empresa
                existing_jobs = _get_existing_jobs(session, company_db.id, company.source)

                # Procesar cada job obtenido
                current_external_ids = set()
                for norm_job in jobs:
                    current_external_ids.add(norm_job.external_id)

                    if norm_job.external_id in existing_jobs:
                        # Actualizar job existente
                        job_db = existing_jobs[norm_job.external_id]
                        _update_job_from_normalized(job_db, norm_job, now)
                        summary.jobs_updated += 1
                    else:
                        # Insertar nuevo job
                        _insert_new_job(session, company_db.id, norm_job, now)
                        summary.jobs_new += 1

                # Marcar como cerrados los jobs que no aparecieron en esta ingesta
                for ext_id, job_db in existing_jobs.items():
                    if ext_id not in current_external_ids and job_db.is_open:
                        job_db.is_open = False
                        # No cambiar status si ya fue reviewed/prepared/applied, solo is_open
                        if job_db.status == JobStatus.NEW:
                            job_db.status = JobStatus.DISCARDED
                        summary.jobs_closed += 1

                session.commit()

            summary.companies_processed += 1
            logger.info(
                f"Empresa {company.name} ({company.source}): "
                f"{len(jobs)} obtenidas, {summary.jobs_new} nuevas, {summary.jobs_updated} actualizadas"
            )

        except Exception as e:
            error = IngestError(
                company_name=company.name,
                source=company.source,
                error_message=str(e)
            )
            summary.errors.append(error)
            logger.error(f"Error ingiriendo {company.name} ({company.source}): {e}", exc_info=True)
            # Continuar con la siguiente empresa

    return summary


def _get_or_create_company(session: Session, company: CompanyConfig) -> Company:
    """Obtiene o crea la empresa en la BD."""
    stmt = select(Company).where(Company.source == company.source, Company.slug == company.slug)
    company_db = session.scalars(stmt).first()

    if company_db is None:
        company_db = Company(
            name=company.name,
            source=company.source,
            slug=company.slug or company.name,
            config_json=company.model_dump(),
        )
        session.add(company_db)
        session.flush()

    return company_db


def _get_existing_jobs(session: Session, company_id: int, source: str) -> dict[str, Job]:
    """Obtiene todos los jobs existentes de una empresa indexados por external_id."""
    stmt = select(Job).where(Job.company_id == company_id, Job.source == source)
    jobs = session.scalars(stmt).all()
    return {job.external_id: job for job in jobs}


def _update_job_from_normalized(job_db: Job, norm_job: NormalizedJob, now: datetime) -> None:
    """Actualiza un job existente con datos normalizados."""
    job_db.last_seen_at = now
    job_db.is_open = True
    job_db.title = norm_job.title
    job_db.location = norm_job.location
    job_db.workplace_type = _as_workplace_type(norm_job.workplace_type)
    job_db.department = norm_job.department
    job_db.description_text = norm_job.description_text
    job_db.url = norm_job.url
    job_db.posted_at = norm_job.posted_at
    job_db.raw_json = norm_job.raw


def _insert_new_job(session: Session, company_id: int, norm_job: NormalizedJob, now: datetime) -> Job:
    """Inserta un nuevo job en la BD."""
    job_db = Job(
        company_id=company_id,
        source=norm_job.source,
        external_id=norm_job.external_id,
        title=norm_job.title,
        location=norm_job.location,
        workplace_type=_as_workplace_type(norm_job.workplace_type),
        department=norm_job.department,
        description_text=norm_job.description_text,
        url=norm_job.url,
        posted_at=norm_job.posted_at,
        first_seen_at=now,
        last_seen_at=now,
        is_open=True,
        status=JobStatus.NEW,
        raw_json=norm_job.raw,
    )
    session.add(job_db)
    return job_db


def probe_company(company: CompanyConfig) -> tuple[bool, int, str | None]:
    """Prueba una empresa individual."""
    source = get_source(company.source)
    config_dict = company.model_dump()
    return source.probe(config_dict)
