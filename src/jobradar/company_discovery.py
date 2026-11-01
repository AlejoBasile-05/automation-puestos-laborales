"""Descubrimiento de empresas de reclutamiento (Fase 7).

Orquesta un proveedor de búsqueda (Brave o Google CSE), extrae los slugs de los
portales de reclutamiento y los deduplica. Los resultados solo se presentan al
usuario; nunca se escriben en ``config.yaml``.

Referencia: PLAN.md Fase 7, AGENTS.md secciones 2, 5 y 11.
"""

from __future__ import annotations

import re
from datetime import datetime

from dotenv import load_dotenv

from jobradar.config import DiscoveryConfig
from jobradar.discovery.base import SearchHit, SearchProvider
from jobradar.discovery.factory import create_search_provider

load_dotenv()  # Carga variables de entorno desde .env

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
    """Descubre empresas de reclutamiento usando un proveedor de búsqueda.

    Extrae slugs de portales de reclutamiento de los resultados y los deduplica.
    Nunca añade empresas automáticamente: solo las presenta al usuario.
    """

    def __init__(
        self,
        api_key: str | None = None,
        config: DiscoveryConfig | None = None,
        provider: SearchProvider | None = None,
    ) -> None:
        self.config = config or DiscoveryConfig()
        self._provider = (
            provider
            if provider is not None
            else create_search_provider(self.config.provider, api_key=api_key)
        )
        # clave -> (momento de la consulta, resultados)
        self._cache: dict[tuple[str, int], tuple[datetime, list[dict[str, str]]]] = {}
        self._queries_made: int = 0

    @property
    def provider_name(self) -> str:
        """Nombre del proveedor de búsqueda activo."""
        return self._provider.name

    def _cache_is_fresh(self, cached_at: datetime) -> bool:
        """Indica si una entrada de caché sigue vigente."""
        age = datetime.now() - cached_at
        return age.total_seconds() < self.config.cache_ttl_hours * 3600

    def discover_companies(
        self, query: str, max_results: int = 10
    ) -> list[dict[str, str]]:
        """Busca empresas de reclutamiento mediante el proveedor activo.

        Args:
            query: Consulta, por ejemplo
                ``site:boards.greenhouse.io "analista financiero" Monterrey``.
            max_results: Máximo de resultados a devolver.

        Returns:
            Lista de diccionarios con las claves ``slug``, ``source``,
            ``company_name``, ``url``, ``source_url`` y ``description``.

        Raises:
            ValueError: si la consulta está vacía o falta una credencial.
            RuntimeError: si se supera el límite de consultas por corrida o si
                el proveedor falla.
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

        self._queries_made += 1
        hits = self._provider.search(clean_query, max_results)

        discovered = self._parse_results(hits)
        self._cache[cache_key] = (datetime.now(), discovered)
        return list(discovered[:max_results])

    def _parse_results(self, hits: list[SearchHit]) -> list[dict[str, str]]:
        """Convierte resultados de búsqueda en empresas candidatas deduplicadas."""
        discovered: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for hit in hits:
            extracted = self._extract_company_info(hit.url)
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
                    "company_name": hit.title or extracted["slug"],
                    "url": extracted["url"],
                    "source_url": hit.url,
                    "description": hit.snippet,
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
    config: DiscoveryConfig | None = None,
) -> list[dict[str, str]]:
    """Función de conveniencia: crea un cliente y busca empresas candidatas."""
    client = CompanyDiscoveryClient(api_key=api_key, config=config)
    return client.discover_companies(query, max_results=max_results)
