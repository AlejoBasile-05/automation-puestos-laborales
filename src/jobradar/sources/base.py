"""Interfaz base para fuentes de vacantes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class NormalizedJob:
    """Vacante normalizada lista para persistir."""
    source: str  # "greenhouse" | "lever" | "workday"
    external_id: str
    company: str  # slug de la empresa
    company_name: str
    title: str
    location: str | None
    workplace_type: str | None  # "remote" | "hybrid" | "onsite" | None
    department: str | None
    description_text: str  # texto plano, sin HTML
    url: str  # enlace para aplicar
    posted_at: datetime | None
    raw: dict  # respuesta original para depurar


class JobSource(ABC):
    """Interfaz base para conectores de fuentes de vacantes."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Nombre identificador de la fuente (greenhouse, lever, workday)."""
        ...

    @abstractmethod
    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene y normaliza las vacantes de una empresa."""
        ...

    @abstractmethod
    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida si un slug existe y cuenta vacantes. Returns (success, count, error)."""
        ...
