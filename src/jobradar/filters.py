"""Prefiltro de vacantes sin LLM."""

from jobradar.config import SearchConfig
from jobradar.sources.base import NormalizedJob


def prefilter_jobs(jobs: list[NormalizedJob], config: SearchConfig) -> list[NormalizedJob]:
    """Aplica prefiltro barato: keywords, ubicación, antigüedad."""
    # TODO: implementar en Fase 1
    raise NotImplementedError("Prefilter not implemented yet")
