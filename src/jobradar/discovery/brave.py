"""Proveedor de búsqueda Brave Search API.

La API key viaja en un header, así que los mensajes de error pueden incluir el
detalle de la excepción sin filtrar el secreto.
"""

import os
import time
from typing import Any

import httpx

from jobradar.discovery.base import SearchHit

BRAVE_SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchProvider:
    """Proveedor de búsqueda sobre Brave Search API."""

    name = "brave"

    def __init__(self, api_key: str | None = None, timeout: float = 20.0) -> None:
        self._api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")
        if not self._api_key:
            raise ValueError(
                "BRAVE_SEARCH_API_KEY no configurada. "
                "Sácala en https://api-dashboard.search.brave.com/register "
                "(servicio de pago: US$ 5 por 1.000 requests, con US$ 5 de "
                "crédito gratis por mes) y añádela al .env"
            )
        self._timeout = timeout
        self._last_request: float = 0.0
        self._min_interval: float = 1.0  # 1 req/s (AGENTS.md §2.4)

    def _rate_limit(self) -> None:
        """Espera lo necesario para no superar 1 request por segundo."""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        """Consulta Brave y devuelve los resultados normalizados."""
        self._rate_limit()

        params: dict[str, str | int] = {"q": query, "count": max_results}
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key or "",
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                response = client.get(
                    BRAVE_SEARCH_API_URL, params=params, headers=headers
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Error llamando a Brave Search API: {exc}") from exc

        results = data.get("web", {}).get("results", []) or []
        return [
            SearchHit(
                url=str(item.get("url", "")),
                title=str(item.get("title") or ""),
                snippet=str(item.get("description") or ""),
            )
            for item in results
        ]
