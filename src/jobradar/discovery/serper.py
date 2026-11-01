"""Proveedor de búsqueda Serper.dev (SERPs de Google vía API comercial).

Verificado contra la API real:
- ``POST https://google.serper.dev/search`` con header ``X-API-KEY``.
- 1 crédito por request (el plan gratuito da 2.500).
- En cuentas gratuitas una consulta con el operador ``site:`` solo admite
  ``num <= 10``; con más devuelve ``400 "Query pattern not allowed for free
  accounts"``. Por eso se pagina con ``page`` en lugar de pedir más de 10.

La API key viaja en un header, no en la URL, así que los mensajes de error no
pueden filtrarla. Aun así no se propaga el ``message`` libre de Serper: podría
incluir texto de la consulta.
"""

import os
import time
from typing import Any

import httpx

from jobradar.discovery.base import SearchHit

SERPER_SEARCH_API_URL = "https://google.serper.dev/search"
SERPER_MAX_RESULTS_PER_PAGE = 10
SERPER_MAX_PAGES = 3


class SerperSearchProvider:
    """Proveedor de búsqueda sobre Serper.dev."""

    name = "serper"

    def __init__(self, api_key: str | None = None, timeout: float = 25.0) -> None:
        self._api_key = api_key or os.getenv("SERPER_API_KEY")
        if not self._api_key:
            raise ValueError(
                "SERPER_API_KEY no configurada. Sácala en https://serper.dev/ "
                "y añádela al .env como SERPER_API_KEY=..."
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
        """Consulta Serper paginando de a 10 resultados como máximo."""
        hits: list[SearchHit] = []
        page = 1

        while len(hits) < max_results and page <= SERPER_MAX_PAGES:
            page_size = min(SERPER_MAX_RESULTS_PER_PAGE, max_results - len(hits))
            batch = self._fetch_page(query, page_size, page)
            hits.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        return hits[:max_results]

    def _fetch_page(self, query: str, page_size: int, page: int) -> list[SearchHit]:
        """Pide una página de resultados a Serper."""
        self._rate_limit()

        payload: dict[str, Any] = {"q": query, "num": page_size}
        if page > 1:
            payload["page"] = page

        headers = {
            "X-API-KEY": self._api_key or "",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                response = client.post(
                    SERPER_SEARCH_API_URL, headers=headers, json=payload
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(self._describe_status(exc.response)) from None
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Error de red llamando a Serper ({type(exc).__name__})"
            ) from None

        organic = data.get("organic") or []
        return [
            SearchHit(
                url=str(item.get("link", "")),
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
            )
            for item in organic
            if item.get("link")
        ]

    @staticmethod
    def _safe_message(response: httpx.Response) -> str:
        """Devuelve el ``message`` de Serper en minúsculas, solo para clasificar."""
        try:
            return str(response.json().get("message") or "").lower()
        except (ValueError, AttributeError):
            return ""

    @classmethod
    def _describe_status(cls, response: httpx.Response) -> str:
        """Traduce el status HTTP a un mensaje accionable."""
        status = response.status_code
        detail = cls._safe_message(response)

        if status in {401, 403}:
            return (
                "Serper rechazó SERPER_API_KEY (HTTP "
                f"{status}): revisá que la key siga activa en https://serper.dev/"
            )
        if status == 429:
            return (
                "Serper devolvió 429: te quedaste sin créditos o superaste el "
                "rate limit. Revisá tu saldo en https://serper.dev/"
            )
        if status == 400 and "pattern not allowed" in detail:
            return (
                "Serper rechazó la consulta (400): en cuentas gratuitas, una "
                "consulta con `site:` solo admite 10 resultados por página"
            )
        if status == 400:
            return "Serper rechazó la consulta (400): revisá la sintaxis del query"
        return f"Serper devolvió HTTP {status}"
