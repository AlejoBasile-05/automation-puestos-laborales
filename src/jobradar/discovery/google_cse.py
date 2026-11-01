"""Proveedor de búsqueda Google Custom Search JSON API.

Requiere **dos** credenciales: ``GOOGLE_API_KEY`` y ``GOOGLE_CSE_ID`` (el ID del
Programmable Search Engine). Sin el ``cx`` la API key no sirve.

Aviso de vigencia: Google cerró esta API a clientes nuevos y la apaga el
2027-01-01 (ver README). El plan gratuito son 100 consultas por día.

Seguridad: la API key viaja en el **query string**, así que nunca se
interpola el texto de la excepción ni la URL del request en los mensajes:
httpx incluiría ``key=...`` en el error.
"""

import os
import time
from typing import Any

import httpx

from jobradar.discovery.base import SearchHit

GOOGLE_CSE_API_URL = "https://www.googleapis.com/customsearch/v1"
GOOGLE_MAX_RESULTS_PER_PAGE = 10  # límite duro de `num`
GOOGLE_MAX_START = 91  # límite duro de `start`


class GoogleCSESearchProvider:
    """Proveedor de búsqueda sobre Google Programmable Search (JSON API)."""

    name = "google_cse"

    def __init__(
        self,
        api_key: str | None = None,
        cse_id: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self._cse_id = cse_id or os.getenv("GOOGLE_CSE_ID")
        if not self._api_key:
            raise ValueError(
                "GOOGLE_API_KEY no configurada. Sácala en "
                "https://console.cloud.google.com/apis/credentials y añádela al "
                ".env como GOOGLE_API_KEY=AIza... (si la pegaste como `key=`, "
                "renómbrala: `key` es el parámetro de la URL, no la variable)"
            )
        if not self._cse_id:
            raise ValueError(
                "GOOGLE_CSE_ID no configurado. Es el ID del Programmable Search "
                "Engine (https://programmablesearchengine.google.com/controlpanel/all) "
                "y va en el .env junto a GOOGLE_API_KEY"
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
        """Consulta Google CSE paginando de a 10 resultados como máximo."""
        hits: list[SearchHit] = []
        start = 1

        while len(hits) < max_results and start <= GOOGLE_MAX_START:
            page_size = min(GOOGLE_MAX_RESULTS_PER_PAGE, max_results - len(hits))
            page = self._fetch_page(query, page_size, start)
            hits.extend(page)
            if len(page) < page_size:
                break
            start += page_size

        return hits[:max_results]

    def _fetch_page(self, query: str, page_size: int, start: int) -> list[SearchHit]:
        """Pide una página de resultados al endpoint de Google."""
        self._rate_limit()

        params: dict[str, str | int] = {
            "key": self._api_key or "",
            "cx": self._cse_id or "",
            "q": query,
            "num": page_size,
            "start": start,
        }

        try:
            with httpx.Client(timeout=httpx.Timeout(self._timeout)) as client:
                response = client.get(
                    GOOGLE_CSE_API_URL,
                    params=params,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            # `from None` para que el traceback no arrastre la URL con la key.
            raise RuntimeError(self._describe_http_error(exc.response)) from None
        except httpx.HTTPError as exc:
            raise RuntimeError(
                "Error de red llamando a Google Custom Search "
                f"({type(exc).__name__})"
            ) from None

        items = data.get("items") or []
        return [
            SearchHit(
                url=str(item.get("link", "")),
                title=str(item.get("title") or ""),
                snippet=str(item.get("snippet") or ""),
            )
            for item in items
            if item.get("link")
        ]

    @staticmethod
    def _error_signals(
        response: httpx.Response,
    ) -> tuple[str | None, str | None, str]:
        """Extrae ``status``, ``reason`` y un texto en minúsculas para clasificar.

        Solo se devuelven enums y un texto normalizado que se usa para comparar:
        nunca se muestra el ``message`` de Google, que podría arrastrar la
        consulta del usuario.
        """
        try:
            error = response.json().get("error", {})
        except (ValueError, AttributeError):
            return None, None, ""
        errors = error.get("errors") or []
        reason = next(
            (item.get("reason") for item in errors if item.get("reason")), None
        )
        message = " ".join(
            str(part)
            for part in [*(item.get("message") for item in errors), error.get("message")]
            if part
        ).lower()
        return error.get("status"), reason, message

    @classmethod
    def _describe_http_error(cls, response: httpx.Response) -> str:
        """Traduce el error HTTP a un mensaje accionable, sin URL ni key."""
        status, reason, message = cls._error_signals(response)
        detail = ", ".join(part for part in (status, reason) if part)

        if "does not have the access" in message or "has not been used" in message:
            return (
                "Tu proyecto de Google Cloud no tiene acceso a Custom Search "
                "JSON API: Google la cerró a clientes nuevos y la apaga el "
                f"2027-01-01. Usá otro proveedor de búsqueda [{detail}]"
            )
        if reason in {"dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"}:
            return (
                "Google Custom Search: cuota agotada (100 consultas/día en el "
                f"plan gratuito) [{detail}]"
            )
        if reason in {"accessNotConfigured", "SERVICE_DISABLED"}:
            return (
                "Google Custom Search no está habilitada en el proyecto de "
                f"Google Cloud (APIs & Services → Enable APIs) [{detail}]"
            )
        if reason in {"keyInvalid", "API_KEY_INVALID", "badRequest"}:
            return f"GOOGLE_API_KEY rechazada por Google: revisá que la key exista [{detail}]"
        if status == "PERMISSION_DENIED" or reason == "forbidden":
            return (
                "Google rechazó la credencial. Revisá en Google Cloud Console "
                "que la API key siga activa y sin restricciones (API restrictions "
                "o application restrictions) que la bloqueen, y que Custom Search "
                f"API esté habilitada [{detail}]"
            )
        return f"Google Custom Search devolvió HTTP {response.status_code} [{detail}]"

