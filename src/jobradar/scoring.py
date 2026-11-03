"""Scoring de compatibilidad con LLM."""

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from rich.console import Console
from sqlalchemy import and_, func, not_, select
from sqlalchemy.orm import joinedload

from jobradar.config import load_config
from jobradar.db.models import Job, Score
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.llm.base import LLMClient
from jobradar.llm.factory import create_llm_client
from jobradar.paths import prompt_path

PROMPT_VERSION = "scoring_v1"
OUTPUT_TOKENS_PER_JOB = 500
console = Console()
CV_MASTER_PATH = Path("data/cv_master.yaml")
PROMPT_PATH = prompt_path("scoring_v1.md")


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


def resolve_run_limit(limit: int | None, configured: int) -> int:
    """Aplica el tope configurable de vacantes por corrida (AGENTS.md §8.4).

    Args:
        limit: Valor pedido por el usuario; ``None`` usa el configurado.
        configured: ``llm.max_jobs_per_run`` leído de ``config.yaml``.

    Returns:
        Cantidad efectiva, nunca negativa ni mayor que ``configured``.
    """
    if limit is None:
        return max(0, configured)
    return max(0, min(limit, configured))


def estimate_text_tokens(text: str) -> int:
    """Estimación burda de tokens: ~4 caracteres por token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    price_input_per_1k: float,
    price_output_per_1k: float,
) -> float:
    """Costo estimado en USD a partir del precio por 1.000 tokens."""
    return (
        (input_tokens / 1000) * price_input_per_1k
        + (output_tokens / 1000) * price_output_per_1k
    )


def current_cv_hash() -> str:
    """Hash SHA256 del CV maestro actual (o del vacío si no existe)."""
    return _compute_cv_hash(_load_cv_master())


def pending_jobs_stats(cv_hash: str | None = None) -> tuple[int, float]:
    """Cuenta de vacantes pendientes y promedio de caracteres de su descripción.

    "Pendiente" significa abierta y sin score para el ``(cv_hash,
    prompt_version)`` actuales, igual que :func:`score_pending`.
    """
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)
    resolved_hash = cv_hash or current_cv_hash()

    pending_filter = not_(
        select(Score.id)
        .where(
            and_(
                Score.job_id == Job.id,
                Score.cv_hash == resolved_hash,
                Score.prompt_version == PROMPT_VERSION,
            )
        )
        .exists()
    )

    with session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(Job).where(Job.is_open).where(pending_filter)
        )
        if not count:
            return 0, 0.0
        total_chars = session.scalar(
            select(func.coalesce(func.sum(func.length(Job.description_text)), 0))
            .where(Job.is_open)
            .where(pending_filter)
        )
    return int(count), float(total_chars or 0) / int(count)


def estimate_scoring_run(limit: int | None = None) -> dict[str, Any]:
    """Estima el volumen y costo de una corrida de scoring antes de ejecutarla.

    El costo en USD solo se calcula si ``config.yaml`` define precios por 1.000
    tokens en ``llm``; si no, se devuelve ``estimated_cost_usd = 0.0`` con
    ``prices_configured = False`` (estimación de tokens únicamente).
    """
    config = load_config()
    try:
        cv_text = _load_cv_master()
    except FileNotFoundError:
        cv_text = ""

    pending, avg_description_chars = pending_jobs_stats(_compute_cv_hash(cv_text))
    cap = resolve_run_limit(limit, config.llm.max_jobs_per_run)
    to_run = min(pending, cap)

    input_tokens = int(to_run * (len(cv_text) + avg_description_chars)) // 4
    output_tokens = to_run * OUTPUT_TOKENS_PER_JOB
    cost = estimate_cost_usd(
        input_tokens,
        output_tokens,
        config.llm.price_input_per_1k_usd,
        config.llm.price_output_per_1k_usd,
    )

    return {
        "pending": pending,
        "limit": cap,
        "to_run": to_run,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": round(cost, 4),
        "prices_configured": bool(
            config.llm.price_input_per_1k_usd or config.llm.price_output_per_1k_usd
        ),
    }


def score_pending(
    limit: int | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict:
    """Punta todas las vacantes pendientes sin score.

    Args:
        limit: Máximo de vacantes a procesar. Si es ``None`` o supera
            ``llm.max_jobs_per_run``, se aplica el tope configurado.
        provider: Proveedor LLM; por defecto el de ``config.yaml``.
        model: Modelo LLM; por defecto el de ``config.yaml``.

    Returns:
        Dict con contadores: scored, cached, errors, total, limit.
    """
    config = load_config()
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    # Resolver límite de ejecución (tope configurable, AGENTS.md §8.4)
    resolved = resolve_run_limit(limit, config.llm.max_jobs_per_run)

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
            .limit(resolved)
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
        "limit": resolved,
    }

