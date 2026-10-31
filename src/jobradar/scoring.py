"""Scoring de compatibilidad con LLM."""

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field
from rich.console import Console
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from jobradar.config import load_config
from jobradar.db.models import Job, Score
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.llm.base import LLMClient
from jobradar.llm.factory import create_llm_client

PROMPT_VERSION = "scoring_v1"
console = Console()
CV_MASTER_PATH = Path("data/cv_master.yaml")
PROMPT_PATH = Path("prompts/scoring_v1.md")


class ScoreOutput(BaseModel):
    """Salida validada del LLM para scoring."""
    score: int = Field(ge=0, le=100, description="Puntuación de 0 a 100")
    verdict: str = Field(description="aplicar | quizá | descartar")
    matches: list[str] = Field(default_factory=list, description="Requisitos cubiertos con evidencia")
    gaps: list[str] = Field(default_factory=list, description="Requisitos no cubiertos")
    red_flags: list[str] = Field(default_factory=list, description="Alertas relevantes")
    language: str = Field(default="es", description="es | en")


def _load_cv_master() -> str:
    """Carga el contenido del CV maestro."""
    if not CV_MASTER_PATH.exists():
        raise FileNotFoundError(f"No se encontró {CV_MASTER_PATH}")
    return CV_MASTER_PATH.read_text(encoding="utf-8")


def _load_prompt() -> str:
    """Carga el prompt de scoring."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"No se encontró {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _compute_cv_hash(cv_text: str) -> str:
    """Calcula SHA256 del CV maestro para caché."""
    return hashlib.sha256(cv_text.encode("utf-8")).hexdigest()


def score_job(
    job: Job,
    cv_hash: str,
    prompt_version: str,
    llm: LLMClient,
    session_factory,
) -> str:
    """Punta una vacante contra el CV maestro.

    Args:
        job: Objeto Job de la BD.
        cv_hash: Hash SHA256 del CV maestro.
        prompt_version: Versión del prompt usado.
        llm: Cliente LLM configurado.
        session_factory: Fábrica de sesiones SQLAlchemy.

    Returns:
        "cached" si ya existía, "scored" si se puntó ahora.
    """
    # Verificar caché
    with session_factory() as session:
        existing = session.scalars(
            select(Score).where(
                Score.job_id == job.id,
                Score.cv_hash == cv_hash,
                Score.prompt_version == prompt_version,
            )
        ).first()
        if existing:
            return "cached"

    # Cargar CV maestro y prompt
    cv_text = _load_cv_master()
    prompt_template = _load_prompt()

    # Construir entrada para el LLM (reemplazo manual para evitar problemas con llaves del JSON en el template)
    user_prompt = (
        prompt_template
        .replace("{cv_master}", cv_text)
        .replace("{job_title}", job.title)
        .replace("{job_description}", job.description_text)
    )
    system_prompt = "Eres un experto reclutador que evalúa compatibilidad de CV contra vacantes. Responde siempre en JSON válido."

    # Llamar al LLM
    result = llm.complete_json(
        system=system_prompt,
        user=user_prompt,
        schema=ScoreOutput,
        temperature=0.0,
    )
    if not isinstance(result, ScoreOutput):
        raise TypeError(f"Se esperaba ScoreOutput, se obtuvo {type(result)}")

    # Guardar en BD
    with session_factory() as session:
        score_db = Score(
            job_id=job.id,
            cv_hash=cv_hash,
            prompt_version=prompt_version,
            model=llm.model_name,
            score=result.score,
            verdict=result.verdict,
            matches_json=result.matches,
            gaps_json=result.gaps,
            red_flags_json=result.red_flags,
        )
        session.add(score_db)
        session.commit()

    return "scored"


def score_pending(
    limit: int = 20,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Punta todas las vacantes pendientes sin score.

    Returns:
        Dict con contadores: scored, cached, errors, total.
    """
    config = load_config()
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    # Crear cliente LLM
    llm = create_llm_client(
        provider=provider or config.llm.provider,
        model=model or config.llm.model_scoring,
    )

    # Calcular hash del CV maestro
    cv_text = _load_cv_master()
    cv_hash = _compute_cv_hash(cv_text)

    # Obtener jobs pendientes (cargar company para evitar DetachedInstanceError)
    with session_factory() as session:
        from sqlalchemy import and_, not_
        stmt = (
            select(Job)
            .options(joinedload(Job.company))
            .where(Job.is_open)
            .where(
                not_(
                    select(Score.id)
                    .where(and_(
                        Score.job_id == Job.id,
                        Score.cv_hash == cv_hash,
                        Score.prompt_version == PROMPT_VERSION,
                    ))
                    .exists()
                )
            )
            .limit(limit)
        )
        jobs = session.scalars(stmt).all()

    scored = 0
    cached = 0
    errors = 0

    for job in jobs:
        try:
            result = score_job(job, cv_hash, PROMPT_VERSION, llm, session_factory)
            if result == "cached":
                cached += 1
            else:
                scored += 1
            console.print(f"  [{scored + cached}/{len(jobs)}] {job.title} (@{job.company.name}) - {result}")
        except Exception as e:
            errors += 1
            console.print(f"  [red]ERROR:[/red] {job.title} (@{job.company.name}): {e}")

    return {
        "scored": scored,
        "cached": cached,
        "errors": errors,
        "total": len(jobs),
    }
