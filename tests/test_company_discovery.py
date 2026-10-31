"""Tests del cliente de descubrimiento de empresas (Fase 7).

Todos los tests mockean HTTP: no hay llamadas de red reales.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from jobradar.company_discovery import (
    BRAVE_SEARCH_API_URL,
    CompanyDiscoveryClient,
    discover_companies,
)
from jobradar.config import DiscoveryConfig


def _make_response(payload: dict[str, Any]) -> MagicMock:
    """Crea un mock de respuesta httpx con JSON válido."""
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _payload(*urls: str) -> dict[str, Any]:
    """Construye una respuesta de Brave Search con las URLs dadas."""
    return {
        "web": {
            "results": [
                {"url": url, "title": f"Empresa {index}", "description": "desc"}
                for index, url in enumerate(urls, start=1)
            ]
        }
    }


@pytest.fixture
def client() -> CompanyDiscoveryClient:
    """Cliente con API key de prueba y sin límite de consultas estricto."""
    return CompanyDiscoveryClient(
        api_key="test_key_123",
        config=DiscoveryConfig(max_queries_per_run=10, cache_ttl_hours=24),
    )


def test_init_with_api_key(client: CompanyDiscoveryClient) -> None:
    """El cliente se inicializa con la API key recibida."""
    assert client.api_key == "test_key_123"
    assert client.headers["X-Subscription-Token"] == "test_key_123"


def test_init_without_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin BRAVE_SEARCH_API_KEY se lanza ValueError con mensaje accionable."""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BRAVE_SEARCH_API_KEY"):
        CompanyDiscoveryClient()


def test_rate_limit_waits_between_requests(
    client: CompanyDiscoveryClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El rate limit duerme lo que falta para completar un segundo."""
    clock = {"now": 100.0}
    sleeps: list[float] = []

    monkeypatch.setattr(
        "jobradar.company_discovery.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "jobradar.company_discovery.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    client._last_request = 100.0
    clock["now"] = 100.25
    client._rate_limit()

    assert sleeps == [pytest.approx(0.75)]


def test_rate_limit_does_not_wait_when_enough_time_passed(
    client: CompanyDiscoveryClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si pasó más de un segundo, no duerme."""
    clock = {"now": 200.0}
    sleeps: list[float] = []

    monkeypatch.setattr(
        "jobradar.company_discovery.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "jobradar.company_discovery.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    client._last_request = 100.0
    clock["now"] = 200.0
    client._rate_limit()

    assert sleeps == []


def test_extract_greenhouse_slug_from_boards(client: CompanyDiscoveryClient) -> None:
    """Extrae el slug de boards.greenhouse.io."""
    assert client._extract_company_info("https://boards.greenhouse.io/empresaejemplo") == {
        "slug": "empresaejemplo",
        "source": "greenhouse",
        "url": "https://boards.greenhouse.io/empresaejemplo",
    }


def test_extract_greenhouse_slug_from_job_boards(
    client: CompanyDiscoveryClient,
) -> None:
    """job-boards no debe confundirse con boards (prefijo compartido)."""
    assert client._extract_company_info(
        "https://job-boards.greenhouse.io/otraempresa"
    ) == {
        "slug": "otraempresa",
        "source": "greenhouse",
        "url": "https://job-boards.greenhouse.io/otraempresa",
    }


def test_extract_greenhouse_ignores_non_slug_segments(
    client: CompanyDiscoveryClient,
) -> None:
    """Segmentos como /jobs no son slugs de tablero."""
    assert client._extract_company_info(
        "https://boards.greenhouse.io/jobs?for=acme"
    ) is None


def test_extract_lever_slug(client: CompanyDiscoveryClient) -> None:
    """Extrae el slug de jobs.lever.co."""
    assert client._extract_company_info("https://jobs.lever.co/empresaejemplo") == {
        "slug": "empresaejemplo",
        "source": "lever",
        "url": "https://jobs.lever.co/empresaejemplo",
    }


def test_extract_workday_tenant_from_cxs_url(client: CompanyDiscoveryClient) -> None:
    """El tenant de Workday se extrae del endpoint cxs."""
    assert client._extract_company_info(
        "https://tsys.wd1.myworkdayjobs.com/wday/cxs/tsys/TSYS/jobs"
    ) == {
        "slug": "tsys",
        "source": "workday",
        "url": "https://tsys.myworkdayjobs.com",
    }


def test_extract_workday_tenant_from_subdomain(client: CompanyDiscoveryClient) -> None:
    """El tenant también se detecta desde el subdominio del portal."""
    assert client._extract_company_info(
        "https://capitalone.wd12.myworkdayjobs.com/Capital_One"
    ) == {
        "slug": "capitalone",
        "source": "workday",
        "url": "https://capitalone.myworkdayjobs.com",
    }


def test_extract_returns_none_for_non_matching_url(
    client: CompanyDiscoveryClient,
) -> None:
    """URLs ajenas a los portales soportados devuelven None."""
    assert client._extract_company_info("https://www.google.com/search?q=test") is None


def test_discover_companies_parses_and_dedupes(
    client: CompanyDiscoveryClient,
) -> None:
    """Parsea los resultados y deduplica por (source, slug)."""
    payload = _payload(
        "https://boards.greenhouse.io/acme",
        "https://boards.greenhouse.io/acme",
        "https://jobs.lever.co/globex",
        "https://example.com/no-es-portal",
    )

    with patch("jobradar.company_discovery.httpx.Client") as client_class:
        http_client = MagicMock()
        client_class.return_value.__enter__.return_value = http_client
        http_client.get.return_value = _make_response(payload)

        results = client.discover_companies("site:boards.greenhouse.io test")

    assert [item["slug"] for item in results] == ["acme", "globex"]
    assert results[0]["source"] == "greenhouse"
    assert results[0]["company_name"] == "Empresa 1"
    assert results[1]["source"] == "lever"
    http_client.get.assert_called_once()
    assert http_client.get.call_args.args[0] == BRAVE_SEARCH_API_URL


def test_discover_companies_uses_cache(
    client: CompanyDiscoveryClient,
) -> None:
    """La segunda consulta idéntica sale de caché y no golpea HTTP."""
    payload = _payload("https://jobs.lever.co/globex")

    with patch("jobradar.company_discovery.httpx.Client") as client_class:
        http_client = MagicMock()
        client_class.return_value.__enter__.return_value = http_client
        http_client.get.return_value = _make_response(payload)

        first = client.discover_companies("consultame")
        second = client.discover_companies("consultame")

    assert first == second
    http_client.get.assert_called_once()


def test_cache_expires_after_ttl(client: CompanyDiscoveryClient) -> None:
    """Una entrada más vieja que cache_ttl_hours se vuelve a consultar."""
    payload = _payload("https://jobs.lever.co/globex")
    stale = datetime.now() - timedelta(hours=DiscoveryConfig().cache_ttl_hours + 1)
    client._cache[("consultame", 10)] = (
        stale,
        [
            {
                "slug": "viejo",
                "source": "lever",
                "company_name": "Viejo",
                "url": "https://jobs.lever.co/viejo",
                "source_url": "https://jobs.lever.co/viejo",
                "description": "",
            }
        ],
    )

    with patch("jobradar.company_discovery.httpx.Client") as client_class:
        http_client = MagicMock()
        client_class.return_value.__enter__.return_value = http_client
        http_client.get.return_value = _make_response(payload)

        results = client.discover_companies("consultame")

    assert [item["slug"] for item in results] == ["globex"]
    http_client.get.assert_called_once()


def test_discover_companies_enforces_max_queries_per_run() -> None:
    """Superar max_queries_per_run lanza RuntimeError."""
    limited = CompanyDiscoveryClient(
        api_key="test_key",
        config=DiscoveryConfig(max_queries_per_run=1),
    )
    payload = _payload("https://jobs.lever.co/globex")

    with patch("jobradar.company_discovery.httpx.Client") as client_class:
        http_client = MagicMock()
        client_class.return_value.__enter__.return_value = http_client
        http_client.get.return_value = _make_response(payload)

        limited.discover_companies("primera")
        with pytest.raises(RuntimeError, match="max_queries_per_run"):
            limited.discover_companies("segunda")

    http_client.get.assert_called_once()


def test_discover_companies_raises_on_empty_query(
    client: CompanyDiscoveryClient,
) -> None:
    """Una consulta vacía es un error de uso."""
    with pytest.raises(ValueError, match="no puede estar vacía"):
        client.discover_companies("   ")


def test_discover_companies_wraps_http_errors(
    client: CompanyDiscoveryClient,
) -> None:
    """Un fallo de red se propaga como RuntimeError."""
    with patch("jobradar.company_discovery.httpx.Client") as client_class:
        http_client = MagicMock()
        client_class.return_value.__enter__.return_value = http_client
        http_client.get.side_effect = httpx.ConnectError("boom")

        with pytest.raises(RuntimeError, match="Brave Search API"):
            client.discover_companies("cualquiera")


def test_module_level_discover_companies_passes_max_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La función de conveniencia propaga max_results al cliente."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, api_key: str | None = None) -> None:
            captured["api_key"] = api_key

        def discover_companies(
            self, query: str, max_results: int = 10
        ) -> list[dict[str, str]]:
            captured["query"] = query
            captured["max_results"] = max_results
            return []

    monkeypatch.setattr(
        "jobradar.company_discovery.CompanyDiscoveryClient", FakeClient
    )

    assert discover_companies("buscar", max_results=3, api_key="k") == []
    assert captured == {"api_key": "k", "query": "buscar", "max_results": 3}
