"""Fuentes de vacantes - factory para obtener conectores."""

from jobradar.sources.base import JobSource
from jobradar.sources.greenhouse import GreenhouseSource
from jobradar.sources.lever import LeverSource
from jobradar.sources.workday import WorkdaySource

_SOURCES: dict[str, type[JobSource]] = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "workday": WorkdaySource,
}


def get_source(source_name: str) -> JobSource:
    """Obtiene una instancia del conector por nombre."""
    source_class = _SOURCES.get(source_name.lower())
    if source_class is None:
        raise ValueError(f"Unknown source: {source_name}. Available: {list(_SOURCES.keys())}")
    return source_class()


def list_sources() -> list[str]:
    """Lista de fuentes disponibles."""
    return list(_SOURCES.keys())

