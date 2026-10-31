"""Prefiltro de vacantes sin LLM."""

from datetime import datetime, timedelta

from jobradar.config import SearchConfig
from jobradar.sources.base import NormalizedJob


def prefilter_jobs(jobs: list[NormalizedJob], config: SearchConfig) -> list[NormalizedJob]:
    """Aplica prefiltro barato: keywords, ubicación, antigüedad.

    Args:
        jobs: Lista de vacantes normalizadas.
        config: Configuración de búsqueda con filtros.

    Returns:
        Lista filtrada de vacantes.
    """
    if not jobs:
        return []

    filtered = []

    # Preparar keywords para búsqueda case-insensitive
    include_keywords = [kw.lower() for kw in config.keywords_include] if config.keywords_include else []
    exclude_keywords = [kw.lower() for kw in config.keywords_exclude] if config.keywords_exclude else []
    allowed_locations = [loc.lower() for loc in config.locations] if config.locations else []

    # Calcular fecha límite para max_age_days
    cutoff_date = None
    if config.max_age_days and config.max_age_days > 0:
        cutoff_date = datetime.utcnow() - timedelta(days=config.max_age_days)

    for job in jobs:
        if _passes_keyword_filter(job, include_keywords, exclude_keywords) \
           and _passes_location_filter(job, allowed_locations, config.accept_remote) \
           and _passes_age_filter(job, cutoff_date):
            filtered.append(job)

    return filtered


def _passes_keyword_filter(
    job: NormalizedJob,
    include_keywords: list[str],
    exclude_keywords: list[str]
) -> bool:
    """Verifica si el título pasa los filtros de keywords."""
    title_lower = job.title.lower() if job.title else ""

    # Debe contener al menos una keyword de inclusión (si hay alguna)
    if include_keywords:
        if not any(kw in title_lower for kw in include_keywords):
            return False

    # No debe contener ninguna keyword de exclusión
    if exclude_keywords:
        if any(kw in title_lower for kw in exclude_keywords):
            return False

    return True


def _passes_location_filter(
    job: NormalizedJob,
    allowed_locations: list[str],
    accept_remote: bool
) -> bool:
    """Verifica si la ubicación pasa el filtro."""
    # Si no hay ubicaciones configuradas, pasar todo
    if not allowed_locations:
        return True

    # Verificar workplace_type remote
    if accept_remote and job.workplace_type == "remote":
        return True

    # Verificar location
    if job.location:
        loc_lower = job.location.lower()
        if any(allowed in loc_lower for allowed in allowed_locations):
            return True

    return False


def _passes_age_filter(job: NormalizedJob, cutoff_date: datetime | None) -> bool:
    """Verifica si la vacante no es demasiado antigua."""
    if cutoff_date is None:
        return True

    if job.posted_at is None:
        # Si no hay fecha, mantener la vacante (benefit of doubt)
        return True

    return job.posted_at >= cutoff_date
