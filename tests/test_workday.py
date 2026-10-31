"""Tests para el conector Workday."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from jobradar.sources.workday import WorkdaySource


def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Crea un mock de respuesta HTTP."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


class TestWorkdaySource:
    """Tests para WorkdaySource."""

    def test_normalize_first_job(self):
        """Verifica normalización del primer job de Workday."""
        source = WorkdaySource()
        raw_job = {
            "title": "Senior Software Engineer",
            "externalPath": "/tsys/job/Senior-Software-Engineer_JR-12345",
            "locationsText": "Atlanta, GA, United States",
            "postedOn": "Posted 2 Days Ago",
            "id": "JR-12345",
        }
        job = source._normalize_job(raw_job, "tsys", "TSYS", "tsys", 1, "TSYS")
        assert job.source == "workday"
        assert job.external_id == "JR-12345"
        assert job.company == "tsys"
        assert job.company_name == "TSYS"
        assert job.title == "Senior Software Engineer"
        assert job.location == "Atlanta, GA, United States"
        assert job.url == "https://tsys.wd1.myworkdayjobs.com/wday/cxs/tsys/TSYS/job/Senior-Software-Engineer_JR-12345"
        assert job.posted_at is not None
        now = datetime.now(UTC)
        expected = now - timedelta(days=2)
        assert abs((job.posted_at - expected).total_seconds()) < 60

    def test_normalize_posted_today(self):
        """Verifica que 'Posted Today' se convierte a hoy."""
        source = WorkdaySource()
        raw_job = {
            "title": "Data Analyst",
            "externalPath": "/tsys/job/Data-Analyst_JR-12346",
            "locationsText": "Remote",
            "postedOn": "Posted Today",
            "id": "JR-12346",
        }
        job = source._normalize_job(raw_job, "tsys", "TSYS", "tsys", 1, "TSYS")
        assert job.posted_at is not None
        now = datetime.now(UTC)
        assert abs((job.posted_at - now).total_seconds()) < 60

    def test_normalize_no_posted_on(self):
        """Verifica manejo de posted_on ausente."""
        source = WorkdaySource()
        raw_job = {
            "title": "Data Analyst",
            "externalPath": "/tsys/job/Data-Analyst_JR-12346",
            "locationsText": "Remote",
            "id": "JR-12346",
        }
        job = source._normalize_job(raw_job, "tsys", "TSYS", "tsys", 1, "TSYS")
        assert job.posted_at is None

    def test_fetch_jobs_success(self):
        """Verifica fetch_jobs con respuesta exitosa."""
        source = WorkdaySource()
        company_config = {
            "slug": "tsys",
            "tenant": "tsys",
            "wd": 1,
            "site": "TSYS",
        }

        list_response = {
            "jobPosts": [
                {
                    "title": "Senior Software Engineer",
                    "externalPath": "/tsys/job/Senior-Software-Engineer_JR-12345",
                    "locationsText": "Atlanta, GA, United States",
                    "postedOn": "Posted 2 Days Ago",
                    "id": "JR-12345",
                }
            ]
        }

        mock_list = _make_mock_response(list_response)
        mock_detail = _make_mock_response(list_response)

        with patch("jobradar.sources.workday.HTTPClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_list
            mock_client.get.return_value = mock_detail

            jobs = source.fetch_jobs(company_config)

            assert len(jobs) == 1
            job = jobs[0]
            assert job.title == "Senior Software Engineer"
            assert job.external_id == "JR-12345"
            assert job.location == "Atlanta, GA, United States"

    def test_fetch_jobs_detail_failure_degrades_gracefully(self):
        """Verifica que un fallo en el detalle no detiene la ingesta."""
        source = WorkdaySource()
        company_config = {
            "slug": "tsys",
            "tenant": "tsys",
            "wd": 1,
            "site": "TSYS",
        }

        list_response = {
            "jobPosts": [
                {
                    "title": "Senior Software Engineer",
                    "externalPath": "/tsys/job/Senior-Software-Engineer_JR-12345",
                    "locationsText": "Atlanta, GA, United States",
                    "postedOn": "Posted 2 Days Ago",
                    "id": "JR-12345",
                }
            ]
        }

        mock_list = _make_mock_response(list_response)
        mock_detail_fail = MagicMock()
        mock_detail_fail.status_code = 500
        mock_detail_fail.raise_for_status.side_effect = Exception("Detail fetch failed")

        with patch("jobradar.sources.workday.HTTPClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_list
            mock_client.get.return_value = mock_detail_fail

            jobs = source.fetch_jobs(company_config)

            assert len(jobs) == 1
            job = jobs[0]
            assert job.title == "Senior Software Engineer"
            assert job.description_text == ""  # Sin detalle, descripción vacía

    def test_probe_success(self):
        """Verifica probe exitoso."""
        source = WorkdaySource()
        company_config = {
            "slug": "tsys",
            "tenant": "tsys",
            "wd": 1,
            "site": "TSYS",
        }

        list_response = {
            "jobPosts": [
                {
                    "title": "Senior Software Engineer",
                    "externalPath": "/tsys/job/Senior-Software-Engineer_JR-12345",
                    "locationsText": "Atlanta, GA, United States",
                    "postedOn": "Posted 2 Days Ago",
                    "id": "JR-12345",
                },
                {
                    "title": "Data Analyst",
                    "externalPath": "/tsys/job/Data-Analyst_JR-12346",
                    "locationsText": "Remote",
                    "postedOn": "Posted Today",
                    "id": "JR-12346",
                },
            ]
        }

        mock_response = _make_mock_response(list_response)

        with patch("jobradar.sources.workday.HTTPClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            ok, count, error = source.probe(company_config)

            assert ok is True
            assert count == 2
            assert error is None

    def test_probe_404(self):
        """Verifica probe con 404 (tenant no encontrado)."""
        source = WorkdaySource()
        company_config = {
            "slug": "nonexistent",
            "tenant": "nonexistent",
            "wd": 1,
            "site": "External",
        }

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("jobradar.sources.workday.HTTPClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.__enter__.return_value = mock_client
            mock_client.post.return_value = mock_response

            ok, count, error = source.probe(company_config)

            assert ok is False
            assert count == 0
            assert error is not None
            assert "404" in error

    def test_probe_exception(self):
        """Verifica probe con excepción de red."""
        source = WorkdaySource()
        company_config = {
            "slug": "tsys",
            "tenant": "tsys",
            "wd": 1,
            "site": "TSYS",
        }

        with patch("jobradar.sources.workday.HTTPClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.__enter__.return_value = mock_client
            mock_client.post.side_effect = Exception("Network error")

            ok, count, error = source.probe(company_config)

            assert ok is False
            assert count == 0
            assert error is not None
            assert "Network error" in error

    def test_missing_config_fields(self):
        """Verifica probe con campos faltantes."""
        source = WorkdaySource()
        company_config = {
            "slug": "tsys",
            # Falta tenant, wd, site
        }

        ok, count, error = source.probe(company_config)

        assert ok is False
        assert count == 0
        assert error is not None
        assert "Missing required" in error

    def test_fetch_jobs_missing_config(self):
        """Verifica fetch_jobs con configuración incompleta."""
        source = WorkdaySource()
        try:
            source.fetch_jobs({"slug": "tsys"})
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            assert "Workday source requires" in str(e)
