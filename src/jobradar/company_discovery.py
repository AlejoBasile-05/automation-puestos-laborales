"""Descubrimiento de empresas de reclutamiento (Fase 7).

Usa la Brave Search API para localizar portales de Greenhouse, Lever y Workday
y extraer sus slugs. Los resultados se presentan al usuario para que decida
cuáles añadir a ``config.yaml``; nunca se modifican automáticamente.

Referencia: PLAN.md Fase 7, AGENTS.md secciones 2, 5 y 11.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv

from jobradar.config import DiscoveryConfig

load_dotenv()  # Carga variables de entorno desde .env

BRAVE_SEARCH_API_URL = "https://api.search.brave.com/res/v1/web/search"

# job-boards debe evaluarse antes que boards: la primera cadena contiene a la segunda.
_JOB_BOARDS_PATTERN = re.compile(r"job-boards\.greenhouse\.io/([^/?#&\s]+)")
_BOARDS_PATTERN = re.compile(r"boards\.greenhouse\.io/([^/?#&\s]+)")
_LEVER_PATTERN = re.compile(r"jobs\.lever\.co/([^/?#&\s]+)")
_WORKDAY_CXS_PATTERN = re.compile(
    r"myworkdayjobs\.com/wday/cxs/([^/?#&\s]+)/([^/?#&\s]+)/jobs"
)
_WORKDAY_SUBDOMAIN_PATTERN = re.compile(
    r"https?://([^./]+)\.wd\d+\.myworkdayjobs\.com"
)

# Segmentos de URL de Greenhouse que no son slugs de tablero.
_NON_SLUG_SEGMENTS = frozenset({"jobs", "jobs.json", "embed", "robots.txt"})


class CompanyDiscoveryClient:
    """Descubre empresas de reclutamiento mediante Brave Search API.

    Extrae slugs de portales de reclutamiento de los resultados de búsqueda.
    Nunca añade empresas automáticamente: solo las presenta al usuario.
    """

    def __init__(
        self,
        api_key: str | None = None,
        config: DiscoveryConfig | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError(
                "BRAVE_SEARCH_API_KEY no configurada. "
                "Obtén una key gratuita en https://search.brave.com/ y añádela al .env"
            )
        self.config = config or DiscoveryConfig()
        self.headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }
        # clave -> (momento de la consulta, resultados)
        self._cache: dict[tuple[str, int], tuple[datetime, list[dict[str, str]]]] = {}
        self._last_request: float = 0.0
        self._min_interval: float = 1.0  # 1 req/s
        self._queries_made: int = 0

    def _rate_limit(self) -> None:
        """Espera lo necesario para no superar 1 request por segundo."""
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _cache_is_fresh(self, cached_at: datetime) -> bool:
        """Indica si una entrada de caché sigue vigente."""
        age = datetime.now() - cached_at
        return age.total_seconds() < self.config.cache_ttl_hours * 3600

    def discover_companies(
        self, query: str, max_results: int = 10
    ) -> list[dict[str, str]]:
        """Busca empresas de reclutamiento mediante la API de búsqueda.

        Args:
            query: Consulta, por ejemplo
                ``site:boards.greenhouse.io "analista financiero" Monterrey``.
            max_results: Máximo de resultados a devolver.

        Returns:
            Lista de diccionarios con las claves ``slug``, ``source``,
            ``company_name``, ``url``, ``source_url`` y ``description``.

        Raises:
            ValueError: si la consulta está vacía.
            RuntimeError: si se supera el límite de consultas por corrida o si
                la API responde con un error.
        """
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("La consulta de búsqueda no puede estar vacía")

        cache_key = (clean_query, max_results)
        cached = self._cache.get(cache_key)
        if cached is not None and self._cache_is_fresh(cached[0]):
            return list(cached[1])

        if self._queries_made >= self.config.max_queries_per_run:
            raise RuntimeError(
                "Se alcanzó el límite de "
                f"{self.config.max_queries_per_run} consultas por corrida "
                "(discovery.max_queries_per_run en config.yaml)"
            )

        self._rate_limit()
        self._queries_made += 1

        params: dict[str, str | int] = {"q": clean_query, "count": max_results}

        try:
            with httpx.Client(timeout=httpx.Timeout(20.0)) as client:
                response = client.get(
                    BRAVE_SEARCH_API_URL,
                    params=params,
                    headers=self.headers,
                )
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Error llamando a Brave Search API: {exc}") from exc

        discovered = self._parse_results(data.get("web", {}).get("results", []))
        self._cache[cache_key] = (datetime.now(), discovered)
        return list(discovered[:max_results])

    def _parse_results(self, results: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Convierte resultados de búsqueda en empresas candidatas deduplicadas."""
        discovered: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for result in results:
            url = str(result.get("url", ""))
            extracted = self._extract_company_info(url)
            if extracted is None:
                continue

            key = (extracted["source"], extracted["slug"])
            if key in seen:
                continue
            seen.add(key)

            discovered.append(
                {
                    "slug": extracted["slug"],
                    "source": extracted["source"],
                    "company_name": str(result.get("title") or extracted["slug"]),
                    "url": extracted["url"],
                    "source_url": url,
                    "description": str(result.get("description") or ""),
                }
            )

        return discovered

    def _extract_company_info(self, url: str) -> dict[str, str] | None:
        """Extrae slug, fuente y URL canónica de un portal de reclutamiento.

        Soporta Greenhouse (``boards`` y ``job-boards``), Lever y Workday.
        Devuelve ``None`` si la URL no pertenece a ninguno de esos portales.
        """
        match = _JOB_BOARDS_PATTERN.search(url)
        if match and match.group(1) not in _NON_SLUG_SEGMENTS:
            return {
                "slug": match.group(1),
                "source": "greenhouse",
                "url": f"https://job-boards.greenhouse.io/{match.group(1)}",
            }

        match = _BOARDS_PATTERN.search(url)
        if match and match.group(1) not in _NON_SLUG_SEGMENTS:
            return {
                "slug": match.group(1),
                "source": "greenhouse",
                "url": f"https://boards.greenhouse.io/{match.group(1)}",
            }

        match = _LEVER_PATTERN.search(url)
        if match:
            return {
                "slug": match.group(1),
                "source": "lever",
                "url": f"https://jobs.lever.co/{match.group(1)}",
            }

        match = _WORKDAY_CXS_PATTERN.search(url)
        if match:
            tenant = match.group(1)
            return {
                "slug": tenant,
                "source": "workday",
                "url": f"https://{tenant}.myworkdayjobs.com",
            }

        match = _WORKDAY_SUBDOMAIN_PATTERN.search(url)
        if match:
            tenant = match.group(1)
            return {
                "slug": tenant,
                "source": "workday",
                "url": f"https://{tenant}.myworkdayjobs.com",
            }

        return None


def discover_companies(
    query: str,
    max_results: int = 10,
    api_key: str | None = None,
) -> list[dict[str, str]]:
    """Función de conveniencia: crea un cliente y busca empresas candidatas."""
    client = CompanyDiscoveryClient(api_key=api_key)
    return client.discover_companies(query, max_results=max_results)
