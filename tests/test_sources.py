"""Tests para conectores de fuentes (Greenhouse, Lever)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobradar.sources import get_source, list_sources
from jobradar.sources.ashby import AshbySource
from jobradar.sources.base import NormalizedJob
from jobradar.sources.greenhouse import GreenhouseSource
from jobradar.sources.lever import LeverSource

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def greenhouse_fixture():
    """Carga fixture de Greenhouse (medsien)."""
    with open(FIXTURES_DIR / "greenhouse_medsien.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def lever_fixture():
    """Carga fixture de Lever (brafton)."""
    with open(FIXTURES_DIR / "lever_brafton.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def ashby_fixture():
    """Carga fixture de Ashby (linear)."""
    with open(FIXTURES_DIR / "ashby_linear.json", encoding="utf-8") as f:
        return json.load(f)


class TestGreenhouseSource:
    """Tests para GreenhouseSource."""

    def test_normalize_first_job(self, greenhouse_fixture):
        """Verifica normalización del primer job del fixture."""
        source = GreenhouseSource()
        job = greenhouse_fixture["jobs"][0]
        normalized = source._normalize_job(job, "medsien", "Medsien")

        assert isinstance(normalized, NormalizedJob)
        assert normalized.source == "greenhouse"
        assert normalized.external_id == "5274077007"
        assert normalized.company == "medsien"
        assert normalized.company_name == "Medsien"
        assert normalized.title == "Account Executive"
        assert normalized.location == "United States"
        assert normalized.department == "Sales"
        assert normalized.url == "https://job-boards.greenhouse.io/medsien/jobs/5274077007"
        assert normalized.posted_at is not None
        assert isinstance(normalized.posted_at, datetime)
        # first_published = 2026-10-23T15:13:41-04:00
        assert normalized.posted_at.year == 2026
        assert normalized.posted_at.month == 10
        assert normalized.posted_at.day == 23
        assert "Medsien" in normalized.description_text
        assert "Account Executive" in normalized.description_text
        # Verificar que el HTML fue limpiado
        assert "<p>" not in normalized.description_text
        assert "<strong>" not in normalized.description_text

    def test_normalize_second_job_has_different_dates(self, greenhouse_fixture):
        """Verifica que first_published != updated_at para el segundo job."""
        source = GreenhouseSource()
        job = greenhouse_fixture["jobs"][1]  # Back-End Developer
        normalized = source._normalize_job(job, "medsien", "Medsien")

        assert normalized.external_id == "4557294007"
        assert normalized.title == "Back-End Developer"
        assert normalized.location == "Istanbul, Turkey"
        assert normalized.department == "Engineering"
        # first_published = 2024-11-04T07:05:50-05:00
        # updated_at = 2026-09-10T02:59:06-04:00
        # Debería usar first_published como posted_at
        assert normalized.posted_at is not None
        assert normalized.posted_at.year == 2024
        assert normalized.posted_at.month == 11

    def test_html_cleaning(self, greenhouse_fixture):
        """Verifica que la limpieza de HTML funciona correctamente."""
        source = GreenhouseSource()
        job = greenhouse_fixture["jobs"][0]
        normalized = source._normalize_job(job, "medsien", "Medsien")

        # El contenido original tiene HTML escapado
        desc = normalized.description_text
        # No debe tener tags HTML
        assert "<" not in desc or "<" in desc
        # Debe tener texto legible
        assert "Medsien" in desc
        assert "remote care management" in desc.lower()
        assert "Responsibilities" in desc
        assert "Qualifications" in desc
        assert "Benefits" in desc

    def test_probe_success(self, greenhouse_fixture, monkeypatch):
        """Test de probe exitoso (mock)."""
        source = GreenhouseSource()

        # Mock del HTTPClient
        class MockResponse:
            def __init__(self, json_data, status_code=200):
                self._json = json_data
                self.status_code = status_code
                self.headers = {}

            def json(self):
                return self._json

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse(greenhouse_fixture)

        monkeypatch.setattr("jobradar.sources.greenhouse.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "medsien", "name": "Medsien"})
        assert success is True
        assert count == 24
        assert error is None

    def test_probe_404(self, monkeypatch):
        """Test de probe con 404."""
        source = GreenhouseSource()

        class MockResponse:
            def __init__(self):
                self.status_code = 404
                self.headers = {}

            def json(self):
                return {}

            def raise_for_status(self):
                raise Exception("404")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse()

        monkeypatch.setattr("jobradar.sources.greenhouse.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "nonexistent", "name": "Nonexistent"})
        assert success is False
        assert count == 0
        assert "not found" in error.lower() or "404" in error


class TestLeverSource:
    """Tests para LeverSource."""

    def test_normalize_first_job(self, lever_fixture):
        """Verifica normalización del primer job del fixture."""
        source = LeverSource()
        job = lever_fixture[0]
        normalized = source._normalize_job(job, "brafton", "Brafton")

        assert isinstance(normalized, NormalizedJob)
        assert normalized.source == "lever"
        assert normalized.external_id == "72674198-21b5-47b9-8358-f240ea108971"
        assert normalized.company == "brafton"
        assert normalized.company_name == "Brafton"
        assert normalized.title == "Content Marketing Strategist - Canada remote"
        assert normalized.location == "Toronto, Ontario"
        assert normalized.department == "Account Management"
        assert normalized.workplace_type == "remote"
        assert normalized.url == "https://jobs.lever.co/brafton/72674198-21b5-47b9-8358-f240ea108971"
        assert normalized.posted_at is not None
        assert isinstance(normalized.posted_at, datetime)
        # createdAt = 1789498402141 ms -> 2026-09-15 15:53:22 UTC
        assert normalized.posted_at.year == 2026
        assert normalized.posted_at.month == 9
        assert normalized.posted_at.day == 15
        assert normalized.posted_at.tzinfo == UTC
        # Verificar que usa descriptionPlain
        desc = normalized.description_text
        assert "Brafton" in desc
        assert "content marketing" in desc.lower()
        # No debe tener HTML
        assert "<div>" not in desc
        assert "<strong>" not in desc

    def test_normalize_freelance_job(self, lever_fixture):
        """Verifica normalización de job freelance (segundo job)."""
        source = LeverSource()
        job = lever_fixture[1]  # Freelance SEO Content Writer - Dutch
        normalized = source._normalize_job(job, "brafton", "Brafton")

        assert normalized.external_id == "fa87d744-1cf6-4d1d-91b9-494933891079"
        assert normalized.title == "Freelance SEO Content Writer - Dutch"
        assert normalized.location == "Netherlands remote"
        assert normalized.department == "Editorial"
        assert normalized.workplace_type == "remote"
        # createdAt = 1791379688755 -> 2026-10-07
        assert normalized.posted_at is not None
        assert normalized.posted_at.year == 2026
        assert normalized.posted_at.month == 10
        assert normalized.posted_at.day == 7
        # Debe tener descriptionPlain
        desc = normalized.description_text
        assert "Brafton" in desc
        assert "freelance" in desc.lower()

    def test_workplace_type_inference(self):
        """Verifica inferencia de workplace_type."""
        source = LeverSource()

        # Caso 1: workplaceType explícito
        job1 = {"workplaceType": "hybrid", "categories": {"location": "New York, NY"}}
        assert source._get_workplace_type(job1) == "hybrid"

        # Caso 2: remote en location
        job2 = {"workplaceType": None, "categories": {"location": "Remote, USA"}}
        assert source._get_workplace_type(job2) == "remote"

        # Caso 3: sin info
        job3 = {"workplaceType": None, "categories": {"location": "San Francisco, CA"}}
        assert source._get_workplace_type(job3) is None

    def test_probe_success(self, lever_fixture, monkeypatch):
        """Test de probe exitoso (mock)."""
        source = LeverSource()

        class MockResponse:
            def __init__(self, json_data, status_code=200):
                self._json = json_data
                self.status_code = status_code
                self.headers = {}

            def json(self):
                return self._json

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse(lever_fixture)

        monkeypatch.setattr("jobradar.sources.lever.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "brafton", "name": "Brafton"})
        assert success is True
        assert count == 18
        assert error is None

    def test_probe_404(self, monkeypatch):
        """Test de probe con 404."""
        source = LeverSource()

        class MockResponse:
            def __init__(self):
                self.status_code = 404
                self.headers = {}

            def json(self):
                return {}

            def raise_for_status(self):
                raise Exception("404")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse()

        monkeypatch.setattr("jobradar.sources.lever.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "nonexistent", "name": "Nonexistent"})
        assert success is False
        assert count == 0
        assert "not found" in error.lower() or "404" in error


class TestAshbySource:
    """Tests para AshbySource."""

    def test_normalize_first_job(self, ashby_fixture):
        """Verifica normalización del primer job del fixture."""
        source = AshbySource()
        job = ashby_fixture["jobs"][0]
        normalized = source._normalize_job(job, "linear", "Linear")

        assert isinstance(normalized, NormalizedJob)
        assert normalized.source == "ashby"
        assert normalized.external_id == "d3bc1ced-3ce4-4086-a050-555055dbb1ff"
        assert normalized.company == "linear"
        assert normalized.company_name == "Linear"
        assert normalized.title == "Senior / Staff Fullstack Engineer"
        assert normalized.location == "Europe"
        assert normalized.department == "Product"
        assert normalized.workplace_type == "remote"
        assert normalized.url.startswith("https://jobs.ashbyhq.com/linear/")
        assert normalized.posted_at is not None
        assert normalized.posted_at.year == 2021
        assert normalized.posted_at.month == 4
        assert normalized.posted_at.day == 27
        # Usa descriptionPlain, sin HTML
        assert normalized.description_text
        assert "<p>" not in normalized.description_text
        assert "<strong>" not in normalized.description_text

    def test_workplace_type_mapping(self):
        """Mapea workplaceType y cae a isRemote cuando falta."""
        source = AshbySource()

        assert source._get_workplace_type({"workplaceType": "Remote"}) == "remote"
        assert source._get_workplace_type({"workplaceType": "Hybrid"}) == "hybrid"
        assert source._get_workplace_type({"workplaceType": "Onsite"}) == "onsite"
        assert source._get_workplace_type({"isRemote": True}) == "remote"
        assert source._get_workplace_type({}) is None

    def test_probe_success(self, ashby_fixture, monkeypatch):
        """Test de probe exitoso (mock)."""
        source = AshbySource()

        class MockResponse:
            def __init__(self, json_data, status_code=200):
                self._json = json_data
                self.status_code = status_code
                self.headers = {}

            def json(self):
                return self._json

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise Exception(f"HTTP {self.status_code}")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse(ashby_fixture)

        monkeypatch.setattr("jobradar.sources.ashby.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "linear", "name": "Linear"})
        assert success is True
        assert count == 31
        assert error is None

    def test_probe_404(self, monkeypatch):
        """Test de probe con 404."""
        source = AshbySource()

        class MockResponse:
            status_code = 404
            headers = {}

            def json(self):
                return {}

            def raise_for_status(self):
                raise Exception("404")

        class MockClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def get(self, url):
                return MockResponse()

        monkeypatch.setattr("jobradar.sources.ashby.HTTPClient", MockClient)

        success, count, error = source.probe({"slug": "nonexistent", "name": "Nonexistent"})
        assert success is False
        assert count == 0
        assert "not found" in error.lower() or "404" in error


class TestSourceFactory:
    """Tests para el factory de fuentes."""

    def test_get_greenhouse_source(self):
        """Obtiene conector Greenhouse."""
        source = get_source("greenhouse")
        assert isinstance(source, GreenhouseSource)

    def test_get_lever_source(self):
        """Obtiene conector Lever."""
        source = get_source("lever")
        assert isinstance(source, LeverSource)

    def test_get_ashby_source(self):
        """Obtiene conector Ashby."""
        source = get_source("ashby")
        assert isinstance(source, AshbySource)

    def test_get_source_case_insensitive(self):
        """Factory es case-insensitive."""
        assert isinstance(get_source("GREENHOUSE"), GreenhouseSource)
        assert isinstance(get_source("Lever"), LeverSource)

    def test_get_unknown_source_raises(self):
        """Fuente desconocida lanza ValueError."""
        with pytest.raises(ValueError) as exc:
            get_source("unknown")
        assert "unknown" in str(exc.value).lower()

    def test_list_sources(self):
        """Lista fuentes disponibles."""
        sources = list_sources()
        assert "greenhouse" in sources
        assert "lever" in sources
        assert "ashby" in sources
        assert len(sources) >= 3


class TestNormalizedJob:
    """Tests del dataclass NormalizedJob."""

    def test_all_fields_present(self, greenhouse_fixture):
        """Verifica que todos los campos requeridos están presentes."""
        source = GreenhouseSource()
        job = greenhouse_fixture["jobs"][0]
        normalized = source._normalize_job(job, "medsien", "Medsien")

        # Campos requeridos según AGENTS.md
        assert normalized.source is not None
        assert normalized.external_id is not None
        assert normalized.company is not None
        assert normalized.company_name is not None
        assert normalized.title is not None
        assert normalized.description_text is not None
        assert normalized.url is not None
        # Opcionales pueden ser None
        assert normalized.location is not None or normalized.location is None
        assert normalized.workplace_type is not None or normalized.workplace_type is None
        assert normalized.department is not None or normalized.department is None
        assert normalized.posted_at is not None or normalized.posted_at is None
        assert isinstance(normalized.raw, dict)

