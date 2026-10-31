"""Orquesta la ingesta de vacantes desde todas las fuentes."""

from typing import Any

from jobradar.config import CompanyConfig
from jobradar.sources.base import JobSource
from jobradar.sources.greenhouse import GreenhouseSource
from jobradar.sources.lever import LeverSource
from jobradar.sources.workday import WorkdaySource


def get_source(source_name: str) -> JobSource:
    """Factory para obtener la fuente correspondiente."""
    sources = {
        "greenhouse": GreenhouseSource(),
        "lever": LeverSource(),
        "workday": WorkdaySource(),
    }
    if source_name not in sources:
        raise ValueError(f"Fuente desconocida: {source_name}")
    return sources[source_name]


def ingest_companies(companies: list[CompanyConfig]) -> dict[str, Any]:
    """Ingesta vacantes de todas las empresas configuradas.

    Returns:
        Dict con resumen: empresas procesadas, vacantes nuevas, cerradas, errores.
    """
    # TODO: implementar en Fase 1
    raise NotImplementedError("Ingest not implemented yet")


def probe_company(company: CompanyConfig) -> tuple[bool, int, str | None]:
    """Prueba una empresa individual."""
    source = get_source(company.source)
    config_dict = company.model_dump()
    return source.probe(config_dict)
