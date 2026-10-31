"""Tests para el módulo de ingesta."""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine

from jobradar.config import CompanyConfig, SearchConfig
from jobradar.db.models import Base, Job
from jobradar.db.session import get_session_factory
from jobradar.filters import prefilter_jobs
from jobradar.ingest import IngestError, IngestSummary, ingest_companies
from jobradar.sources.base import NormalizedJob


@pytest.fixture
def engine():
    """Engine en memoria para tests."""
    return create_engine("sqlite:///:memory:", echo=False)


@pytest.fixture
def session_factory(engine):
    """Session factory para tests."""
    Base.metadata.create_all(engine)
    return get_session_factory(engine)


@pytest.fixture
def sample_greenhouse_jobs():
    """Jobs normalizados de ejemplo (Greenhouse)."""
    return [
        NormalizedJob(
            source="greenhouse",
            external_id="gh_123",
            company="medsien",
            company_name="Medsien",
            title="Financial Analyst",
            location="Monterrey, NL, Mexico",
            workplace_type="remote",
            department="Finance",
            description_text="We are looking for a Financial Analyst...",
            url="https://boards.greenhouse.io/medsien/jobs/123",
            posted_at=datetime.utcnow() - timedelta(days=2),
            raw={"id": "123", "title": "Financial Analyst"},
        ),
        NormalizedJob(
            source="greenhouse",
            external_id="gh_456",
            company="medsien",
            company_name="Medsien",
            title="Senior Financial Analyst",
            location="Remote",
            workplace_type="remote",
            department="Finance",
            description_text="Senior role for Financial Analyst...",
            url="https://boards.greenhouse.io/medsien/jobs/456",
            posted_at=datetime.utcnow() - timedelta(days=5),
            raw={"id": "456", "title": "Senior Financial Analyst"},
        ),
    ]


@pytest.fixture
def sample_lever_jobs():
    """Jobs normalizados de ejemplo (Lever)."""
    return [
        NormalizedJob(
            source="lever",
            external_id="lv_789",
            company="brafton",
            company_name="Brafton",
            title="Content Marketing Manager",
            location="Mexico City",
            workplace_type="hybrid",
            department="Marketing",
            description_text="Content Marketing Manager role...",
            url="https://jobs.lever.co/brafton/789",
            posted_at=datetime.utcnow() - timedelta(days=1),
            raw={"id": "789", "text": "Content Marketing Manager"},
        ),
    ]


@pytest.fixture
def companies_config():
    """Configuración de empresas de prueba."""
    return [
        CompanyConfig(name="Medsien", source="greenhouse", slug="medsien"),
        CompanyConfig(name="Brafton", source="lever", slug="brafton"),
    ]


class TestIngest:
    """Tests para la función ingest_companies."""

    def test_ingest_new_jobs(self, session_factory, sample_greenhouse_jobs, companies_config):
        """Test ingesta de jobs nuevos."""
        with patch("jobradar.ingest.get_source") as mock_get_source:
            mock_source = Mock()
            mock_source.fetch_jobs.return_value = sample_greenhouse_jobs
            mock_get_source.return_value = mock_source

            # Ejecutar ingesta
            summary = ingest_companies([companies_config[0]], session_factory=session_factory)

            assert summary.companies_processed == 1
            assert summary.jobs_new == 2
            assert summary.jobs_updated == 0
            assert summary.jobs_closed == 0
            assert not summary.has_errors()

            # Verificar en BD
            with session_factory() as session:
                jobs = session.query(Job).all()
                assert len(jobs) == 2
                assert all(j.is_open for j in jobs)
                assert all(j.status == "new" for j in jobs)

    def test_ingest_upsert_updates_existing(self, session_factory, sample_greenhouse_jobs, companies_config):
        """Test que segunda ingesta actualiza en lugar de duplicar."""
        with patch("jobradar.ingest.get_source") as mock_get_source:
            mock_source = Mock()
            mock_source.fetch_jobs.return_value = sample_greenhouse_jobs
            mock_get_source.return_value = mock_source

            # Primera ingesta
            summary1 = ingest_companies([companies_config[0]], session_factory=session_factory)
            assert summary1.jobs_new == 2

            # Segunda ingesta con mismos jobs
            summary2 = ingest_companies([companies_config[0]], session_factory=session_factory)
            assert summary2.jobs_new == 0
            assert summary2.jobs_updated == 2
            assert summary2.jobs_closed == 0

            # Verificar en BD - solo 2 jobs totales
            with session_factory() as session:
                jobs = session.query(Job).all()
                assert len(jobs) == 2

    def test_ingest_marks_missing_as_closed(self, session_factory, sample_greenhouse_jobs, companies_config):
        """Test que jobs que desaparecen se marcan is_open=False."""
        with patch("jobradar.ingest.get_source") as mock_get_source:
            mock_source = Mock()
            mock_get_source.return_value = mock_source

            # Primera ingesta con 2 jobs
            mock_source.fetch_jobs.return_value = sample_greenhouse_jobs
            summary1 = ingest_companies([companies_config[0]], session_factory=session_factory)
            assert summary1.jobs_new == 2

            # Segunda ingesta con solo 1 job (el otro desapareció)
            mock_source.fetch_jobs.return_value = [sample_greenhouse_jobs[0]]
            summary2 = ingest_companies([companies_config[0]], session_factory=session_factory)

            assert summary2.jobs_new == 0
            assert summary2.jobs_updated == 1
            assert summary2.jobs_closed == 1

            # Verificar en BD
            with session_factory() as session:
                jobs = session.query(Job).all()
                assert len(jobs) == 2
                open_jobs = [j for j in jobs if j.is_open]
                closed_jobs = [j for j in jobs if not j.is_open]
                assert len(open_jobs) == 1
                assert len(closed_jobs) == 1
                assert closed_jobs[0].status == "discarded"

    def test_ingest_error_handling_continues(self, session_factory, companies_config):
        """Test que un error en una empresa no detiene las demás."""
        # El session_factory del fixture ya tiene las tablas creadas
        # Pero necesitamos resetear la BD para este test
        # Usar la misma session_factory pero limpiar antes

        with patch("jobradar.ingest.get_source") as mock_get_source:
            # Primera empresa falla, segunda OK
            def side_effect(source_name):
                if source_name == "greenhouse":
                    raise Exception("API Error")
                mock_source = Mock()
                mock_source.fetch_jobs.return_value = [
                    NormalizedJob(
                        source="lever",
                        external_id="lv_1",
                        company="brafton",
                        company_name="Brafton",
                        title="Test Job",
                        location="Remote",
                        workplace_type="remote",
                        department="Test",
                        description_text="Desc",
                        url="http://test.com",
                        posted_at=datetime.utcnow(),
                        raw={},
                    )
                ]
                return mock_source

            mock_get_source.side_effect = side_effect

            summary = ingest_companies(companies_config, session_factory=session_factory)

            assert summary.companies_processed == 1  # solo la que no falló
            assert summary.jobs_new == 1
            assert summary.has_errors()
            assert len(summary.errors) == 1
            assert summary.errors[0].company_name == "Medsien"
            assert "API Error" in summary.errors[0].error_message


class TestPrefilterJobs:
    """Tests para el prefiltro de vacantes."""

    def test_filter_by_keywords_include(self):
        """Test filtro keywords_include."""
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Financial Analyst", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="2", company="test", company_name="Test",
                title="Software Engineer", location="Remote", workplace_type="remote",
                department="Engineering", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
        ]
        config = SearchConfig(keywords_include=["financial", "analyst"])

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 1
        assert filtered[0].title == "Financial Analyst"

    def test_filter_by_keywords_exclude(self):
        """Test filtro keywords_exclude."""
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Senior Financial Analyst", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="2", company="test", company_name="Test",
                title="Financial Analyst", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
        ]
        config = SearchConfig(keywords_exclude=["senior", "lead"])

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 1
        assert filtered[0].title == "Financial Analyst"

    def test_filter_by_location(self):
        """Test filtro por ubicación."""
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Job 1", location="Monterrey, NL", workplace_type="onsite",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="2", company="test", company_name="Test",
                title="Job 2", location="Mexico City", workplace_type="onsite",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="3", company="test", company_name="Test",
                title="Job 3", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow(), raw={}
            ),
        ]
        config = SearchConfig(locations=["monterrey"], accept_remote=True)

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 2  # Monterrey + Remote
        titles = {j.title for j in filtered}
        assert "Job 1" in titles
        assert "Job 3" in titles

    def test_filter_by_max_age_days(self):
        """Test filtro por antigüedad."""
        now = datetime.utcnow()
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Recent Job", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=2), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="2", company="test", company_name="Test",
                title="Old Job", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=10), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="3", company="test", company_name="Test",
                title="No Date Job", location="Remote", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=None, raw={}
            ),
        ]
        config = SearchConfig(max_age_days=7)

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 2  # Recent + No Date (benefit of doubt)
        titles = {j.title for j in filtered}
        assert "Recent Job" in titles
        assert "No Date Job" in titles

    def test_filter_combined(self):
        """Test combinación de filtros."""
        now = datetime.utcnow()
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Financial Analyst", location="Monterrey", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=2), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="2", company="test", company_name="Test",
                title="Senior Financial Analyst", location="Monterrey", workplace_type="remote",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=2), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="3", company="test", company_name="Test",
                title="Software Engineer", location="Monterrey", workplace_type="remote",
                department="Engineering", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=2), raw={}
            ),
            NormalizedJob(
                source="greenhouse", external_id="4", company="test", company_name="Test",
                title="Financial Analyst", location="Mexico City", workplace_type="onsite",
                department="Finance", description_text="Desc", url="http://test.com",
                posted_at=now - timedelta(days=10), raw={}
            ),
        ]
        config = SearchConfig(
            keywords_include=["financial"],
            keywords_exclude=["senior"],
            locations=["monterrey"],
            accept_remote=True,
            max_age_days=7,
        )

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 1
        assert filtered[0].title == "Financial Analyst"
        assert filtered[0].external_id == "1"

    def test_filter_empty_config_passes_all(self):
        """Test que config vacía pasa todo."""
        jobs = [
            NormalizedJob(
                source="greenhouse", external_id="1", company="test", company_name="Test",
                title="Any Job", location="Anywhere", workplace_type="onsite",
                department="Any", description_text="Desc", url="http://test.com",
                posted_at=datetime.utcnow() - timedelta(days=100), raw={}
            ),
        ]
        config = SearchConfig(
            keywords_include=[],
            keywords_exclude=[],
            locations=[],
            accept_remote=True,
            max_age_days=0,
        )

        filtered = prefilter_jobs(jobs, config)
        assert len(filtered) == 1


class TestIngestSummary:
    """Tests para IngestSummary."""

    def test_total_jobs(self):
        summary = IngestSummary(jobs_new=5, jobs_updated=3)
        assert summary.total_jobs() == 8

    def test_has_errors(self):
        summary = IngestSummary()
        assert not summary.has_errors()
        summary.errors.append(IngestError("Test", "greenhouse", "Error"))
        assert summary.has_errors()
