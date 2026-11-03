"""Consultas y acciones de datos del dashboard (AGENTS.md sección 12).

Toda la lógica de acceso a datos vive aquí; ``app/dashboard.py`` solo pinta.
"""

import csv
import io
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from jobradar.applications import get_application_artifacts, prepare_application
from jobradar.config import load_config
from jobradar.db.models import (
    Application,
    Company,
    Event,
    Job,
    JobStatus,
    Score,
    WorkplaceType,
)
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.ingest import IngestSummary, ingest_companies
from jobradar.scoring import estimate_scoring_run, score_pending

LAST_VISIT_FILE = Path("data/last_visit.json")

SessionFactory = Callable[[], Session]

# Inyectable en tests para no tocar data/jobradar.sqlite.
_session_factory_override: SessionFactory | None = None


def set_session_factory_for_testing(factory: SessionFactory | None) -> None:
    """Reemplaza la fábrica de sesiones (solo para tests)."""
    global _session_factory_override
    _session_factory_override = factory


def _get_session_factory() -> SessionFactory:
    """Devuelve la fábrica de sesiones activa."""
    if _session_factory_override is not None:
        return _session_factory_override
    engine = get_engine()
    init_db(engine)
    return cast(SessionFactory, get_session_factory(engine))


class JobFilters(BaseModel):
    """Filtros de la tabla de vacantes del dashboard."""

    search_text: str | None = None
    company: str | None = None
    source: str | None = None
    location: str | None = None
    remote: bool = False
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    only_open: bool = False
    min_score: int | None = None


# ---------------------------------------------------------------------------
# Consultas de vacantes
# ---------------------------------------------------------------------------


def get_filtered_jobs(
    filters: JobFilters | None = None,
    last_visit: datetime | None = None,
    sort: str = "recientes",
) -> list[Job]:
    """Obtiene vacantes filtradas y marca las publicadas tras ``last_visit``.

    Args:
        filters: Filtros de la tabla; ``min_score`` exige un score vigente >= ese valor.
        last_visit: Marca para calcular ``job.is_new``.
        sort: ``"recientes"`` (por fecha, por defecto) o ``"puntaje"`` (mayor primero).
    """
    active = filters or JobFilters()
    session_factory = _get_session_factory()

    with session_factory() as session:
        stmt = select(Job).join(Company, Job.company_id == Company.id)

        if active.search_text and active.search_text.strip():
            pattern = f"%{active.search_text.strip()}%"
            stmt = stmt.where(
                or_(Job.title.ilike(pattern), Job.description_text.ilike(pattern))
            )
        if active.company and active.company.strip():
            stmt = stmt.where(Company.name.ilike(f"%{active.company.strip()}%"))
        if active.source and active.source.strip():
            stmt = stmt.where(Job.source == active.source.strip().lower())
        if active.location and active.location.strip():
            stmt = stmt.where(Job.location.ilike(f"%{active.location.strip()}%"))
        if active.remote:
            stmt = stmt.where(Job.workplace_type == WorkplaceType.REMOTE)
        if active.date_from is not None:
            stmt = stmt.where(
                Job.posted_at >= datetime.combine(active.date_from, dt_time.min)
            )
        if active.date_to is not None:
            stmt = stmt.where(
                Job.posted_at <= datetime.combine(active.date_to, dt_time.max)
            )
        if active.status:
            desired = _coerce_status(active.status)
            if desired is not None:
                stmt = stmt.where(Job.status == desired)
        if active.only_open:
            stmt = stmt.where(Job.is_open.is_(True))

        stmt = stmt.order_by(Job.posted_at.desc().nullslast(), Job.first_seen_at.desc())
        jobs = list(session.execute(stmt).scalars().all())

        for job in jobs:
            # Fuerza la carga de la relación antes de cerrar la sesión.
            _ = job.company.name if job.company else None
            job.is_new = bool(
                last_visit is not None
                and job.posted_at is not None
                and job.posted_at > last_visit
            )

    if active.min_score is not None or sort == "puntaje":
        scores = get_scores_for_jobs([job.id for job in jobs])
        if active.min_score is not None:
            jobs = [
                job
                for job in jobs
                if scores.get(job.id, {}).get("score", -1) >= active.min_score
            ]
        if sort == "puntaje":
            jobs.sort(
                key=lambda job: (
                    scores.get(job.id, {}).get("score", -1),
                    job.posted_at or datetime.min,
                ),
                reverse=True,
            )

    return jobs


def get_job_details(job_id: int) -> Job | None:
    """Devuelve una vacante por ID con su empresa cargada."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is not None and job.company is not None:
            _ = job.company.name
        return job


def get_scores_for_jobs(job_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Devuelve el último score de cada vacante pedida.

    Se resuelve en una sola consulta para no hacer N+1 desde el dashboard.

    Args:
        job_ids: IDs de vacantes visibles.

    Returns:
        Mapa ``job_id -> score`` con la fila más reciente por vacante. Un ID
        sin score simplemente no aparece en el resultado.
    """
    if not job_ids:
        return {}

    session_factory = _get_session_factory()
    with session_factory() as session:
        rows = session.scalars(
            select(Score)
            .where(Score.job_id.in_(job_ids))
            .order_by(
                Score.created_at.desc(),
                Score.id.desc(),
            )
        ).all()

    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.job_id in latest:
            continue
        latest[row.job_id] = {
            "score": row.score,
            "verdict": row.verdict,
            "matches": row.matches_json or [],
            "gaps": row.gaps_json or [],
            "red_flags": row.red_flags_json or [],
            "model": row.model,
            "created_at": row.created_at,
        }
    return latest


def run_scoring(limit: int | None = None) -> dict[str, Any]:
    """Puntúa vacantes pendientes respetando ``llm.max_jobs_per_run``."""
    return score_pending(limit=limit)


def run_cost_estimate(limit: int | None = None) -> dict[str, Any]:
    """Estima tokens y costo de la próxima corrida de scoring (sin llamar al LLM)."""
    return estimate_scoring_run(limit=limit)


def get_job_events(job_id: int) -> list[Event]:
    """Devuelve el historial de eventos de una vacante, del más reciente al más viejo."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        stmt = (
            select(Event)
            .where(Event.job_id == job_id)
            .order_by(Event.created_at.desc())
        )
        return list(session.execute(stmt).scalars().all())


def get_jobs_by_status() -> dict[str, int]:
    """Conteo de vacantes por estado."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        stmt = select(Job.status, func.count(Job.id)).group_by(Job.status)
        rows = session.execute(stmt).all()
        return {str(status): int(count) for status, count in rows}


def get_all_jobs_with_status(status_filter: str | None = None) -> list[dict[str, Any]]:
    """Lista de vacantes con estado, empresa, fechas y notas de postulación."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        stmt = (
            select(Job, Company.name, Application.applied_at, Application.notes)
            .join(Company, Job.company_id == Company.id)
            .outerjoin(Application, Application.job_id == Job.id)
            .order_by(Job.first_seen_at.desc())
        )
        if status_filter:
            desired = _coerce_status(status_filter)
            if desired is not None:
                stmt = stmt.where(Job.status == desired)

        rows = session.execute(stmt).all()

    return [
        {
            "id": job.id,
            "title": job.title,
            "company": company_name,
            "company_name": company_name,
            "source": job.source,
            "status": str(job.status),
            "posted_at": job.posted_at.strftime("%Y-%m-%d") if job.posted_at else None,
            "applied_at": applied_at.strftime("%Y-%m-%d") if applied_at else None,
            "notes": notes or "",
        }
        for job, company_name, applied_at, notes in rows
    ]


def get_jobs_without_response(days: int) -> list[dict[str, Any]]:
    """Vacantes aplicadas sin respuesta tras ``days`` días."""
    session_factory = _get_session_factory()
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)

    with session_factory() as session:
        stmt = (
            select(Job, Company.name, Application.applied_at)
            .join(Company, Job.company_id == Company.id)
            .join(Application, Application.job_id == Job.id)
            .where(
                Job.status == JobStatus.APPLIED,
                Application.applied_at.is_not(None),
                Application.applied_at < cutoff,
            )
            .order_by(Application.applied_at.asc())
        )
        rows = session.execute(stmt).all()

    return [
        {
            "id": job.id,
            "title": job.title,
            "company": company_name,
            "applied_at": applied_at.strftime("%Y-%m-%d") if applied_at else None,
        }
        for job, company_name, applied_at in rows
    ]


# ---------------------------------------------------------------------------
# Acciones de estado
# ---------------------------------------------------------------------------


def mark_job_reviewed(job_id: int) -> None:
    """Marca una vacante como revisada y registra el evento."""
    _change_status(job_id, JobStatus.REVIEWED)


def mark_job_discarded(job_id: int) -> None:
    """Marca una vacante como descartada y registra el evento."""
    _change_status(job_id, JobStatus.DISCARDED)


def _latest_application(session: Session, job_id: int) -> Application | None:
    """Devuelve la postulación más reciente de una vacante.

    Una vacante puede tener varias ``Application`` (cada regeneración del CV
    inserta una nueva), así que nunca se usa ``scalar_one_or_none``.
    """
    stmt = (
        select(Application)
        .where(Application.job_id == job_id)
        .order_by(Application.created_at.desc(), Application.id.desc())
    )
    return session.execute(stmt).scalars().first()


def mark_job_applied(job_id: int) -> None:
    """Marca una vacante como aplicada y registra el evento.

    Si ya existe una postulación preparada (``applied_at`` vacío) se le pone la
    fecha; si ya estaba aplicada se rechaza para no duplicar el envío.
    """
    session_factory = _get_session_factory()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Vacante {job_id} no encontrada")

        application = _latest_application(session, job_id)
        if application is not None and application.applied_at is not None:
            raise ValueError(f"Ya existe una aplicación para la vacante {job_id}")

        old_status = job.status
        job.status = JobStatus.APPLIED

        if application is None:
            session.add(
                Application(
                    job_id=job_id,
                    tailored_cv_json={},
                    message_text="",
                    language="es",
                    required_coverage=0.0,
                    applied_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
        else:
            application.applied_at = datetime.now(UTC).replace(tzinfo=None)

        session.add(
            Event(
                job_id=job_id,
                type="status_change",
                payload_json={"old": str(old_status), "new": JobStatus.APPLIED.value},
            )
        )
        session.commit()


def _change_status(job_id: int, new_status: JobStatus) -> None:
    """Cambia el estado de una vacante registrando el evento correspondiente."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Vacante {job_id} no encontrada")

        old_status = job.status
        job.status = new_status
        session.add(
            Event(
                job_id=job_id,
                type="status_change",
                payload_json={"old": str(old_status), "new": new_status.value},
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Notas de postulación
# ---------------------------------------------------------------------------


def get_application_notes(job_id: int) -> str:
    """Devuelve las notas de la postulación más reciente de una vacante."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        application = _latest_application(session, job_id)
        return application.notes or "" if application is not None else ""


def set_application_notes(job_id: int, notes: str) -> None:
    """Guarda las notas de postulación, creando la aplicación si no existe."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        application = _latest_application(session, job_id)

        if application is None:
            if not notes.strip():
                return
            session.add(
                Application(
                    job_id=job_id,
                    tailored_cv_json={},
                    message_text="",
                    language="es",
                    required_coverage=0.0,
                    notes=notes,
                )
            )
        else:
            application.notes = notes

        session.commit()


def save_application_message(application_id: int, message: str) -> None:
    """Guarda el mensaje de postulación editado en la UI."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            raise ValueError(f"Aplicación {application_id} no encontrada")
        application.message_text = message
        session.commit()


# ---------------------------------------------------------------------------
# Preparación de postulaciones
# ---------------------------------------------------------------------------


def run_prepare_application(job_id: int) -> dict[str, Any]:
    """Wrapper para preparar la postulación de una vacante."""
    return prepare_application(job_id)


def get_application_artifacts_query(job_id: int) -> dict[str, Any] | None:
    """Wrapper para obtener los artefactos de la postulación."""
    return get_application_artifacts(job_id)


def run_ingest() -> IngestSummary:
    """Ejecuta la ingesta de vacantes de las empresas configuradas."""
    config = load_config()
    return ingest_companies(config.companies, session_factory=_get_session_factory())


def get_last_visit() -> datetime | None:
    """Devuelve la marca de la última visita, si existe."""
    if LAST_VISIT_FILE.exists():
        raw = LAST_VISIT_FILE.read_text(encoding="utf-8").strip()
        if raw:
            return datetime.fromisoformat(raw)
    return None


def set_last_visit(timestamp: datetime) -> None:
    """Guarda la marca de la última visita."""
    LAST_VISIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_VISIT_FILE.write_text(timestamp.isoformat(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------------------


def export_jobs_to_csv() -> str:
    """Exporta el seguimiento de vacantes a CSV como cadena."""
    session_factory = _get_session_factory()
    with session_factory() as session:
        stmt = (
            select(Job, Company.name, Application.applied_at, Application.notes)
            .join(Company, Job.company_id == Company.id)
            .outerjoin(Application, Application.job_id == Job.id)
            .order_by(Job.first_seen_at.desc())
        )
        rows = session.execute(stmt).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "job_id",
            "titulo",
            "empresa",
            "fuente",
            "estado",
            "fecha_publicacion",
            "fecha_aplicacion",
            "notas",
        ]
    )
    for job, company_name, applied_at, notes in rows:
        writer.writerow(
            [
                job.id,
                job.title,
                company_name,
                job.source,
                job.status,
                job.posted_at.strftime("%Y-%m-%d") if job.posted_at else "",
                applied_at.strftime("%Y-%m-%d") if applied_at else "",
                notes or "",
            ]
        )
    return output.getvalue()


def _coerce_status(value: str) -> JobStatus | None:
    """Convierte un texto de estado en ``JobStatus``, o ``None`` si no es válido."""
    try:
        return JobStatus(value.strip().lower())
    except ValueError:
        return None
