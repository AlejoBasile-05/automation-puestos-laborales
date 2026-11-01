"""Tests de los proveedores de búsqueda (Brave y Google CSE).

Sin red: todo el transporte httpx está mockeado.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from jobradar.company_discovery import CompanyDiscoveryClient
from jobradar.discovery.brave import BRAVE_SEARCH_API_URL, BraveSearchProvider
from jobradar.discovery.factory import create_search_provider
from jobradar.discovery.google_cse import (
    GOOGLE_CSE_API_URL,
    GoogleCSESearchProvider,
)
from jobradar.discovery.serper import SERPER_SEARCH_API_URL, SerperSearchProvider

SERPER_FIXTURE = Path("tests/fixtures/serper_search.json")

SECRET = "SECRET_KEY_123"


def _response(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def _mock_client(monkeypatch: pytest.MonkeyPatch, module: str) -> MagicMock:
    """Parchea httpx.Client en el módulo indicado y devuelve el cliente mock."""
    http_client = MagicMock()
    client_class = MagicMock()
    client_class.return_value.__enter__.return_value = http_client
    monkeypatch.setattr(f"{module}.httpx.Client", client_class)
    return http_client


# ---------------------------------------------------------------------------
# Brave
# ---------------------------------------------------------------------------


def test_brave_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin key se falla con un mensaje que nombra la variable."""
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BRAVE_SEARCH_API_KEY"):
        BraveSearchProvider()


def test_brave_parses_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mapea web.results a SearchHit y manda la key en el header."""
    provider = BraveSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.brave")
    http_client.get.return_value = _response(
        {
            "web": {
                "results": [
                    {
                        "url": "https://jobs.lever.co/acme",
                        "title": "Acme",
                        "description": "desc",
                    }
                ]
            }
        }
    )

    hits = provider.search("consulta", 5)

    assert [hit.url for hit in hits] == ["https://jobs.lever.co/acme"]
    assert hits[0].title == "Acme"
    assert hits[0].snippet == "desc"
    kwargs = http_client.get.call_args.kwargs
    assert kwargs["headers"]["X-Subscription-Token"] == SECRET
    assert http_client.get.call_args.args[0] == BRAVE_SEARCH_API_URL


def test_brave_rate_limit_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """El rate limit duerme lo que falta para completar un segundo."""
    provider = BraveSearchProvider(api_key=SECRET)
    clock = {"now": 100.0}
    sleeps: list[float] = []

    monkeypatch.setattr(
        "jobradar.discovery.brave.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "jobradar.discovery.brave.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    provider._last_request = 100.0
    clock["now"] = 100.25
    provider._rate_limit()

    assert sleeps == [pytest.approx(0.75)]


def test_brave_wraps_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un fallo de red se convierte en RuntimeError."""
    provider = BraveSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.brave")
    http_client.get.side_effect = httpx.ConnectError("boom")

    with pytest.raises(RuntimeError, match="Brave Search API"):
        provider.search("x", 5)


# ---------------------------------------------------------------------------
# Google CSE
# ---------------------------------------------------------------------------


def test_google_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin GOOGLE_API_KEY se falla con mensaje accionable."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_API_KEY") as excinfo:
        GoogleCSESearchProvider(cse_id="cx")

    # Pista para el error clásico de pegar `key=...` en el .env.
    assert "renómbrala" in str(excinfo.value)


def test_google_requires_cse_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con key pero sin cx se falla nombrando GOOGLE_CSE_ID."""
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_CSE_ID"):
        GoogleCSESearchProvider(api_key=SECRET)


def test_google_parses_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google usa `link`/`snippet`, no `url`/`description`."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = _response(
        {
            "items": [
                {
                    "link": "https://job-boards.greenhouse.io/acme",
                    "title": "Acme",
                    "snippet": "desc",
                }
            ]
        }
    )

    hits = provider.search("consulta", 5)

    assert [hit.url for hit in hits] == ["https://job-boards.greenhouse.io/acme"]
    assert hits[0].title == "Acme"
    assert hits[0].snippet == "desc"
    params = http_client.get.call_args.kwargs["params"]
    assert params["q"] == "consulta"
    assert params["cx"] == "cx"
    assert params["num"] == 5
    assert params["start"] == 1
    assert http_client.get.call_args.args[0] == GOOGLE_CSE_API_URL


def test_google_paginates_when_limit_exceeds_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con límite 15 hace dos requests: start=1 y start=11."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.side_effect = [
        _response(
            {"items": [{"link": f"https://jobs.lever.co/e{i}"} for i in range(10)]}
        ),
        _response(
            {"items": [{"link": f"https://jobs.lever.co/f{i}"} for i in range(5)]}
        ),
    ]

    hits = provider.search("consulta", 15)

    assert len(hits) == 15
    calls = http_client.get.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["params"]["start"] == 1
    assert calls[0].kwargs["params"]["num"] == 10
    assert calls[1].kwargs["params"]["start"] == 11
    assert calls[1].kwargs["params"]["num"] == 5


def test_google_stops_when_page_is_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la página trae menos de lo pedido, no sigue paginando."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = _response(
        {"items": [{"link": "https://jobs.lever.co/acme"}]}
    )

    hits = provider.search("consulta", 20)

    assert len(hits) == 1
    http_client.get.assert_called_once()


def test_google_ignores_items_without_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un item sin `link` no produce un hit vacío."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = _response(
        {"items": [{"title": "sin link"}, {"link": "https://jobs.lever.co/acme"}]}
    )

    hits = provider.search("x", 5)

    assert [hit.url for hit in hits] == ["https://jobs.lever.co/acme"]


def _status_error(
    status_code: int, payload: dict[str, Any] | None = None
) -> httpx.HTTPStatusError:
    """Construye un HTTPStatusError con cuerpo de error opcional."""
    request = httpx.Request("GET", "https://www.googleapis.com/customsearch/v1")
    response = httpx.Response(status_code, json=payload, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_google_quota_error_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    """`dailyLimitExceeded` se traduce a un mensaje sobre la cuota diaria."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = MagicMock(
        raise_for_status=MagicMock(
            side_effect=_status_error(
                403,
                {
                    "error": {
                        "status": "RESOURCE_EXHAUSTED",
                        "errors": [{"reason": "dailyLimitExceeded"}],
                    }
                },
            )
        )
    )

    with pytest.raises(RuntimeError, match="cuota agotada"):
        provider.search("x", 5)


def test_google_forbidden_points_at_the_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`forbidden`/PERMISSION_DENIED acusa a la key, no a la cuota."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = MagicMock(
        raise_for_status=MagicMock(
            side_effect=_status_error(
                403,
                {
                    "error": {
                        "status": "PERMISSION_DENIED",
                        "errors": [{"reason": "forbidden"}],
                    }
                },
            )
        )
    )

    with pytest.raises(RuntimeError, match="credencial"):
        provider.search("x", 5)


def test_google_closed_api_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """El caso real "does not have the access" se reporta como API cerrada."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    google_message = (
        "This project does not have the access to Custom Search JSON API."
    )
    http_client.get.return_value = MagicMock(
        raise_for_status=MagicMock(
            side_effect=_status_error(
                403,
                {
                    "error": {
                        "status": "PERMISSION_DENIED",
                        "errors": [{"reason": "forbidden", "message": google_message}],
                    }
                },
            )
        )
    )

    with pytest.raises(RuntimeError, match="no tiene acceso") as excinfo:
        provider.search("x", 5)

    # El texto libre de Google no se propaga: podría arrastrar la consulta.
    assert google_message not in str(excinfo.value)


def test_google_disabled_api_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """`accessNotConfigured` señala que falta habilitar la API."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.return_value = MagicMock(
        raise_for_status=MagicMock(
            side_effect=_status_error(
                403,
                {
                    "error": {
                        "status": "PERMISSION_DENIED",
                        "errors": [{"reason": "accessNotConfigured"}],
                    }
                },
            )
        )
    )

    with pytest.raises(RuntimeError, match="no está habilitada"):
        provider.search("x", 5)


def test_google_never_leaks_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ni el mensaje ni el traceback encadenado exponen la key."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    http_client = _mock_client(monkeypatch, "jobradar.discovery.google_cse")
    http_client.get.side_effect = httpx.ConnectError(
        f"failed for url https://www.googleapis.com/customsearch/v1?key={SECRET}"
    )

    with pytest.raises(RuntimeError) as excinfo:
        provider.search("x", 5)

    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert SECRET not in repr(excinfo.value)


def test_google_rate_limit_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google también respeta 1 req/s."""
    provider = GoogleCSESearchProvider(api_key=SECRET, cse_id="cx")
    clock = {"now": 50.0}
    sleeps: list[float] = []

    monkeypatch.setattr(
        "jobradar.discovery.google_cse.time.monotonic", lambda: clock["now"]
    )
    monkeypatch.setattr(
        "jobradar.discovery.google_cse.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    provider._last_request = 50.0
    clock["now"] = 50.4
    provider._rate_limit()

    assert sleeps == [pytest.approx(0.6)]


def test_factory_builds_serper_provider() -> None:
    """`serper` construye el proveedor de Serper."""
    provider = create_search_provider("serper", api_key=SECRET)
    assert isinstance(provider, SerperSearchProvider)
    assert provider.name == "serper"


# ---------------------------------------------------------------------------
# Serper
# ---------------------------------------------------------------------------


def test_serper_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin SERPER_API_KEY se falla con mensaje accionable."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="SERPER_API_KEY"):
        SerperSearchProvider()


def test_serper_parses_real_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Parsea una respuesta real de Serper (`organic[].link/title/snippet`)."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    payload = json.loads(SERPER_FIXTURE.read_text(encoding="utf-8"))
    http_client.post.return_value = _response(payload)

    hits = provider.search("consulta", 5)

    assert len(hits) == 5
    assert hits[0].url == "https://boards.greenhouse.io/livecareer/jobs/8230595"
    assert hits[0].title
    assert http_client.post.call_args.args[0] == SERPER_SEARCH_API_URL
    headers = http_client.post.call_args.kwargs["headers"]
    assert headers["X-API-KEY"] == SECRET


def test_serper_caps_num_at_ten_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pedir 15 hace dos requests: num=10 y después num=5 con page=2."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.side_effect = [
        _response({"organic": [{"link": f"https://jobs.lever.co/a{i}"} for i in range(10)]}),
        _response({"organic": [{"link": f"https://jobs.lever.co/b{i}"} for i in range(5)]}),
    ]

    hits = provider.search("consulta", 15)

    assert len(hits) == 15
    calls = http_client.post.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["json"] == {"q": "consulta", "num": 10}
    assert calls[1].kwargs["json"] == {"q": "consulta", "num": 5, "page": 2}


def test_serper_stops_when_page_is_short(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la página trae menos de lo pedido, no sigue paginando."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.return_value = _response(
        {"organic": [{"link": "https://jobs.lever.co/acme"}]}
    )

    hits = provider.search("consulta", 20)

    assert len(hits) == 1
    http_client.post.assert_called_once()


def test_serper_ignores_items_without_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un item sin `link` no produce un hit vacío."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.return_value = _response(
        {"organic": [{"title": "sin link"}, {"link": "https://jobs.lever.co/acme"}]}
    )

    hits = provider.search("x", 5)

    assert [hit.url for hit in hits] == ["https://jobs.lever.co/acme"]


def test_serper_rejects_bad_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """401/403 se reportan como credencial rechazada."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.return_value = MagicMock(
        raise_for_status=MagicMock(side_effect=_status_error(401))
    )

    with pytest.raises(RuntimeError, match="SERPER_API_KEY"):
        provider.search("x", 5)


def test_serper_reports_exhausted_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 se traduce a saldo/rate limit."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.return_value = MagicMock(
        raise_for_status=MagicMock(side_effect=_status_error(429))
    )

    with pytest.raises(RuntimeError, match="créditos"):
        provider.search("x", 5)


def test_serper_explains_free_account_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """El 400 real de cuentas gratuitas se explica con su causa."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.return_value = MagicMock(
        raise_for_status=MagicMock(
            side_effect=_status_error(
                400, {"message": "Query pattern not allowed for free accounts."}
            )
        )
    )

    with pytest.raises(RuntimeError, match="site:"):
        provider.search("x", 5)


def test_serper_never_leaks_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """La key no aparece en el mensaje ni en el traceback encadenado."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    http_client.post.side_effect = httpx.ConnectError(
        f"failed for header X-API-KEY: {SECRET}"
    )

    with pytest.raises(RuntimeError) as excinfo:
        provider.search("x", 5)

    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


def test_serper_end_to_end_extracts_slugs(monkeypatch: pytest.MonkeyPatch) -> None:
    """El fixture real termina en slugs de Greenhouse válidos."""
    provider = SerperSearchProvider(api_key=SECRET)
    http_client = _mock_client(monkeypatch, "jobradar.discovery.serper")
    payload = json.loads(SERPER_FIXTURE.read_text(encoding="utf-8"))
    http_client.post.return_value = _response(payload)

    client = CompanyDiscoveryClient(provider=provider)
    results = client.discover_companies("site:boards.greenhouse.io test", 10)

    slugs = {item["slug"] for item in results}
    assert {"livecareer", "imafinancialgroup", "berkadia"} <= slugs
    assert all(item["source"] == "greenhouse" for item in results)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_builds_google_provider() -> None:
    """`google_cse` construye el proveedor de Google."""
    provider = create_search_provider("google_cse", api_key=SECRET, cse_id="cx")
    assert isinstance(provider, GoogleCSESearchProvider)
    assert provider.name == "google_cse"


def test_factory_builds_brave_provider() -> None:
    """`brave` construye el proveedor de Brave."""
    provider = create_search_provider("brave", api_key=SECRET)
    assert isinstance(provider, BraveSearchProvider)
    assert provider.name == "brave"


def test_factory_rejects_unknown_provider() -> None:
    """Un proveedor inexistente falla enumerando los válidos."""
    with pytest.raises(ValueError, match="brave, google_cse"):
        create_search_provider("duckduckgo")
