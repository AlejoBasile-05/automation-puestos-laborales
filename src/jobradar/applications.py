"""Orquestación de la preparación de postulaciones (AGENTS.md §9.1 y §10).

Une extracción de requisitos, matching determinista, knockouts, tailoring,
render PDF/DOCX y verificación ATS. La UI solo llama a estas funciones.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobradar.ats_check import generate_ats_report, save_ats_report
from jobradar.ats_keywords import ensure_requirements, match_keywords
from jobradar.config import load_config
from jobradar.db.models import Application, Event, Job, JobRequirement, JobStatus
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.knockouts import check_knockouts
from jobradar.llm.base import LLMClient
from jobradar.llm.factory import create_llm_client
from jobradar.render.docx import generate_docx
from jobradar.render.pdf import generate_pdf
from jobradar.tailoring import tailor_job

CV_MASTER_PATH = "data/cv_master.yaml"
OUTPUT_ROOT = "output"


def _sanitize_segment(value: str) -> str:
    """Convierte texto libre en un segmento seguro y determinista de ruta."""
    normalized = unicodedata.normalize("NFD", value)
    without_marks = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", without_marks).lower()
    return cleaned.strip("_") or "sin_nombre"


def _output_dir_for(job: Job) -> str:
    """Directorio de salida ``output/{empresa}_{puesto}_{YYYYMMDD}``."""
    company_slug = job.company.slug if job.company and job.company.slug else "empresa"
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    folder = f"{_sanitize_segment(company_slug)}_{_sanitize_segment(job.title or 'puesto')}_{stamp}"
    return str(Path(OUTPUT_ROOT) / folder)


def _latest_application(session: Session, job_id: int) -> Application | None:
    """Devuelve la aplicación más reciente de una vacante."""
    stmt = (
        select(Application)
        .where(Application.job_id == job_id)
        .order_by(Application.created_at.desc(), Application.id.desc())
    )
    return session.execute(stmt).scalars().first()


def _original_bullets(tailored: dict[str, Any]) -> list[str]:
    """Bullets reescritos del CV adaptado, para el chequeo de ida y vuelta."""
    bullets: list[str] = []
    for experience in tailored.get("experience", []):
        for bullet_id in experience.get("bullet_ids", []):
            rewrite = experience.get("rewrites", {}).get(bullet_id)
            if rewrite:
                bullets.append(rewrite)
    return bullets


def prepare_application(
    job_id: int,
    llm: LLMClient | None = None,
    writing_llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Genera CV adaptado, mensaje, PDF/DOCX y reporte ATS de una vacante.

    Args:
        job_id: ID de la vacante.
        llm: Cliente para la extracción de requisitos (inyectable en tests).
        writing_llm: Cliente para el tailoring (inyectable en tests).

    Returns:
        Diccionario con ``exito``, rutas generadas, reporte ATS, cobertura,
        keywords soportadas/brechas y knockouts evaluados.
    """
    config = load_config()
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            return {"exito": False, "error": f"Vacante {job_id} no encontrada"}
        output_dir = _output_dir_for(job)

    extraction_llm = llm or create_llm_client(
        provider=config.llm.provider, model=config.llm.model_scoring
    )

    try:
        extraction = ensure_requirements(job, session_factory, extraction_llm)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        return {"exito": False, "error": f"No se pudieron extraer requisitos: {exc}"}

    keywords = extraction.get("keywords", [])
    knockouts = extraction.get("knockouts", [])

    try:
        keyword_results = match_keywords(keywords, CV_MASTER_PATH)
        knockout_results = check_knockouts(knockouts, CV_MASTER_PATH)
    except FileNotFoundError as exc:
        return {"exito": False, "error": f"Falta el CV maestro: {exc}"}

    supported = [item for item in keyword_results if item["status"] == "supported"]
    gaps = [item for item in keyword_results if item["status"] == "gap"]

    tailoring = tailor_job(
        job_id=job_id,
        keywords_supported=supported,
        knockouts=knockout_results,
        llm=writing_llm,
        language=extraction.get("language", "es"),
    )
    if not tailoring.get("exito"):
        return {
            "exito": False,
            "error": tailoring.get("error", "Falló la generación del CV"),
            "keywords_supported": supported,
            "keywords_gap": gaps,
            "knockouts": knockout_results,
        }

    tailored = tailoring["tailored"]
    application_id = tailoring["application_id"]

    try:
        pdf_path = generate_pdf(tailored, output_dir, CV_MASTER_PATH)
        docx_path = generate_docx(tailored, output_dir, CV_MASTER_PATH)
        report = generate_ats_report(
            pdf_path=pdf_path,
            docx_path=docx_path,
            original_bullets=_original_bullets(tailored),
            keywords=tailored.get("keywords_used", []),
            max_pages=config.ats.max_pages,
            umbral=config.ats.min_required_coverage,
        )
        save_ats_report(report, output_dir)
    except Exception as exc:  # noqa: BLE001 - el fallo se reporta a la UI
        return {
            "exito": False,
            "error": f"Falló la generación de documentos: {exc}",
            "application_id": application_id,
        }

    with session_factory() as session:
        application = session.get(Application, application_id)
        if application is None:
            return {"exito": False, "error": "La aplicación generada no existe"}
        application.pdf_path = pdf_path
        application.docx_path = docx_path
        application.ats_report_json = report
        application.message_text = tailored.get("cover_message", "")
        application.language = extraction.get("language", "es")

        job = session.get(Job, job_id)
        if job is not None and job.status in {JobStatus.NEW, JobStatus.REVIEWED}:
            old_status = job.status
            job.status = JobStatus.PREPARED
            session.add(
                Event(
                    job_id=job_id,
                    type="status_change",
                    payload_json={
                        "old": str(old_status),
                        "new": JobStatus.PREPARED.value,
                    },
                )
            )
        session.commit()

    return {
        "exito": True,
        "application_id": application_id,
        "pdf_path": pdf_path,
        "docx_path": docx_path,
        "ats_report": report,
        "required_coverage": tailoring["required_coverage"],
        "overall_coverage": tailoring["overall_coverage"],
        "tailored": tailored,
        "keywords_supported": supported,
        "keywords_gap": gaps,
        "knockouts": knockout_results,
        "language": extraction.get("language", "es"),
        "output_dir": output_dir,
    }


def get_application_artifacts(job_id: int) -> dict[str, Any] | None:
    """Devuelve la última postulación preparada con su contexto ATS.

    No llama al LLM: usa la caché de ``job_requirements`` y el matching
    determinista. Si no hay postulación, devuelve ``None``.
    """
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    with session_factory() as session:
        application = _latest_application(session, job_id)
        if application is None:
            return None

        tailored = application.tailored_cv_json or {}
        requirements = session.execute(
            select(JobRequirement)
            .where(JobRequirement.job_id == job_id)
            .order_by(JobRequirement.created_at.desc(), JobRequirement.id.desc())
        ).scalars().first()

        keywords: list[dict[str, Any]] = []
        knockouts: list[dict[str, Any]] = []
        if requirements is not None:
            stored = requirements.keywords_json or {}
            raw_keywords = stored.get("keywords", []) if isinstance(stored, dict) else stored
            raw_knockouts: list[dict[str, Any]] = cast(
                list[dict[str, Any]], requirements.knockouts_json or []
            )
            try:
                keywords = match_keywords(raw_keywords, CV_MASTER_PATH)
                knockouts = check_knockouts(raw_knockouts, CV_MASTER_PATH)
            except FileNotFoundError:
                keywords = []
                knockouts = []

        return {
            "application_id": application.id,
            "created_at": application.created_at,
            "pdf_path": application.pdf_path,
            "docx_path": application.docx_path,
            "message_text": application.message_text,
            "language": application.language,
            "required_coverage": application.required_coverage,
            "ats_report": application.ats_report_json or {},
            "tailored": tailored,
            "keywords": keywords,
            "knockouts": knockouts,
            "applied_at": application.applied_at,
        }
