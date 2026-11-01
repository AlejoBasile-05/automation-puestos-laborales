"""Selección del proveedor de búsqueda según ``config.yaml``."""

from jobradar.discovery.base import SearchProvider
from jobradar.discovery.brave import BraveSearchProvider
from jobradar.discovery.google_cse import GoogleCSESearchProvider
from jobradar.discovery.serper import SerperSearchProvider

_VALID_PROVIDERS = ("brave", "google_cse", "serper")


def create_search_provider(
    name: str,
    *,
    api_key: str | None = None,
    cse_id: str | None = None,
    timeout: float = 20.0,
) -> SearchProvider:
    """Crea el proveedor de búsqueda pedido.

    Args:
        name: ``brave`` | ``google_cse``.
        api_key: Credencial explícita; si es ``None`` se lee del entorno.
        cse_id: ID del Programmable Search Engine (solo Google).
        timeout: Timeout HTTP en segundos.

    Raises:
        ValueError: si el proveedor no existe o falta una credencial.
    """
    provider = name.strip().lower()

    if provider == "brave":
        return BraveSearchProvider(api_key=api_key, timeout=timeout)
    if provider == "google_cse":
        return GoogleCSESearchProvider(
            api_key=api_key, cse_id=cse_id, timeout=timeout
        )
    if provider == "serper":
        return SerperSearchProvider(api_key=api_key, timeout=timeout)

    raise ValueError(
        f"Proveedor de búsqueda desconocido: {name}. "
        f"Opciones válidas: {', '.join(_VALID_PROVIDERS)}"
    )
