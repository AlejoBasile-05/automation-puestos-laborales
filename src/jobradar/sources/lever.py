"""Conector Lever (stub)."""

from typing import Any

from jobradar.sources.base import JobSource, NormalizedJob


class LeverSource(JobSource):
    """Conector para Lever."""

    @property
    def source_name(self) -> str:
        return "lever"

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Lever."""
        # TODO: implementar en Fase 1
        raise NotImplementedError("Lever connector not implemented yet")

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida slug de Lever."""
        # TODO: implementar en Fase 1
        raise NotImplementedError("Lever probe not implemented yet")
