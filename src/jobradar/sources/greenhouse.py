"""Conector Greenhouse (stub)."""

from typing import Any

from jobradar.sources.base import JobSource, NormalizedJob


class GreenhouseSource(JobSource):
    """Conector para Greenhouse."""

    @property
    def source_name(self) -> str:
        return "greenhouse"

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Greenhouse."""
        # TODO: implementar en Fase 1
        raise NotImplementedError("Greenhouse connector not implemented yet")

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida slug de Greenhouse."""
        # TODO: implementar en Fase 1
        raise NotImplementedError("Greenhouse probe not implemented yet")
