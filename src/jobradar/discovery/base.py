"""Contrato común de los proveedores de búsqueda web.

Cada proveedor devuelve resultados crudos (URL, título y snippet). La lógica
de negocio —extraer slugs, deduplicar, cachear— vive en
``jobradar.company_discovery`` y no sabe qué proveedor está detrás.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchHit:
    """Un resultado de búsqueda, independiente del proveedor."""

    url: str
    title: str = ""
    snippet: str = ""


@runtime_checkable
class SearchProvider(Protocol):
    """Proveedor de búsqueda web."""

    name: str

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        """Devuelve hasta ``max_results`` resultados para la consulta."""
        ...
