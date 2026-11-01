"""Proveedores de búsqueda web para el descubrimiento de empresas."""

from jobradar.discovery.base import SearchHit, SearchProvider
from jobradar.discovery.factory import create_search_provider

__all__ = ["SearchHit", "SearchProvider", "create_search_provider"]
