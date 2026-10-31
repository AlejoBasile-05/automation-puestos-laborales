"""Conector Workday (stub - fase extra)."""

from typing import Any

from jobradar.sources.base import JobSource, NormalizedJob


class WorkdaySource(JobSource):
    """Conector para Workday (fase extra)."""

    @property
    def source_name(self) -> str:
        return "workday"

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Workday."""
        # TODO: implementar en Fase 6
        raise NotImplementedError("Workday connector not implemented yet")

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida tenant de Workday."""
        # TODO: implementar en Fase 6
        raise NotImplementedError("Workday probe not implemented yet")
