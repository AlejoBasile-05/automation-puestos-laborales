"""Tests de la orquestación de postulaciones (AGENTS.md §9.1 y §10).

Sin red y sin tokens: LLM falso, render simulado y SQLite en memoria.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import jobradar.applications as applications
import jobradar.tailoring as tailoring
from jobradar.applications import get_application_artifacts, prepare_application
from jobradar.ats_keywords import ATSExtraction
from jobradar.db.models import Application, Base, Company, Event, Job, JobStatus
from jobradar.llm.base import LLMClient
from jobradar.tailoring import TailoredCVOutput, TailoredExperience

CV_MASTER_TEST_PATH = "tests/fixtures/cv_master_test.yaml"


class FakeLLMClient(LLMClient):
    """Cliente LLM falso que devuelve resultados preparados."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append({"system": system, "user": user, "schema": schema})
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    @property
    def model_name(self) -> str:
        return "fake-model"


def _extraction() -> ATSExtraction:
    """Extracción válida con una keyword soportada y una brecha."""
    return ATSExtraction.model_validate(
        {
            "job_title_exact": "Financial Analyst",
            "language": "en",
            "keywords": [
                {
                    "term": "Power BI",
                    "type": "tool",
                    "importance": "required",
                    "synonyms": ["PowerBI"],
                    "frequency_in_posting": 3,
                },
                {
                    "term": "Excel",
                    "type": "tool",
                    "importance": "required",
                    "synonyms": [],
                    "frequency_in_posting": 2,
                },
            ],
            "knockouts": [
                {
                    "type": "years_experience",
                    "requirement": "3+ años en FP&A",
                    "value": 3,
                    "area": "FP&A",
                    "mandatory": True,
                }
            ],
        }
    )


def _tailored() -> TailoredCVOutput:
    """CV adaptado válido contra tests/fixtures/cv_master_test.yaml."""
    return TailoredCVOutput(
        headline="Desarrollador",
        summary="Experiencia en Power BI",
        experience=[
            TailoredExperience(
                experience_id="exp_test_1",
                bullet_ids=["exp_test_1_b1"],
                rewrites={
                    "exp_test_1_b1": (
                        "Desarrollé aplicaciones con Power BI y planeación y "
                        "análisis financiero (FP&A)."
                    )
                },
            )
        ],
        skills=["Power BI"],
        education_ids=["edu_test_1"],
        keywords_used=["Power BI"],
        cover_message="Mensaje breve de postulación.",
    )


@pytest.fixture
def engine():
    """Motor SQLite en memoria."""
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def session_factory(engine, monkeypatch: pytest.MonkeyPatch):
    """Fábrica en memoria inyectada en applications y tailoring."""
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(applications, "get_engine", lambda: engine)
    monkeypatch.setattr(applications, "init_db", lambda _engine: None)
    monkeypatch.setattr(applications, "get_session_factory", lambda _engine: factory)
    monkeypatch.setattr(tailoring, "get_engine", lambda: engine)
    monkeypatch.setattr(tailoring, "init_db", lambda _engine: None)
    monkeypatch.setattr(tailoring, "get_session_factory", lambda _engine: factory)
    monkeypatch.setattr(applications, "CV_MASTER_PATH", CV_MASTER_TEST_PATH)
    monkeypatch.setattr(tailoring, "CV_MASTER_PATH", Path(CV_MASTER_TEST_PATH))
    return factory


@pytest.fixture
def job(session_factory) -> Job:
    """Vacante de prueba."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_factory() as session:
        company = Company(name="Acme", source="greenhouse", slug="acme", config_json={})
        session.add(company)
        session.flush()
        record = Job(
            company_id=company.id,
            source="greenhouse",
            external_id="gh-1",
            title="Financial Analyst",
            location="Remote",
            workplace_type=None,
            department=None,
            description_text="We need 3+ years of FP&A and Power BI and Excel.",
            url="https://example.test/gh-1",
            posted_at=now,
            first_seen_at=now,
            last_seen_at=now,
            is_open=True,
            status=JobStatus.NEW,
            raw_json={},
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        _ = record.id
    return record


def _patch_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """Sustituye render y ATS por dobles que no escriben archivos."""
    paths = {
        "pdf": str(tmp_path / "Test_User_CV.pdf"),
        "docx": str(tmp_path / "Test_User_CV.docx"),
    }
    for path in paths.values():
        Path(path).write_bytes(b"fake")

    report = {
        "pdf_extractable": (True, "ok"),
        "reading_order": (True, "ok"),
        "keyword_coverage": (True, "ok"),
    }

    monkeypatch.setattr(applications, "generate_pdf", lambda *a, **k: paths["pdf"])
    monkeypatch.setattr(applications, "generate_docx", lambda *a, **k: paths["docx"])
    monkeypatch.setattr(applications, "generate_ats_report", lambda *a, **k: report)
    monkeypatch.setattr(applications, "save_ats_report", lambda *a, **k: "ats.json")
    return paths


def test_prepare_application_success(
    session_factory, job, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prepara la postulación, guarda artefactos y cambia el estado."""
    _patch_render(monkeypatch, tmp_path)
    extraction_llm = FakeLLMClient([_extraction()])
    writing_llm = FakeLLMClient([_tailored()])

    result = prepare_application(
        job_id=job.id, llm=extraction_llm, writing_llm=writing_llm
    )

    assert result["exito"] is True
    assert result["application_id"]
    assert "acme_financial_analyst" in result["output_dir"]
    assert result["required_coverage"] == 1.0
    assert [kw["term"] for kw in result["keywords_supported"]] == ["Power BI"]
    assert [kw["term"] for kw in result["keywords_gap"]] == ["Excel"]

    with session_factory() as session:
        application = session.get(Application, result["application_id"])
        assert application is not None
        assert application.pdf_path == result["pdf_path"]
        assert application.docx_path == result["docx_path"]
        assert application.message_text == "Mensaje breve de postulación."
        assert application.language == "en"

        prepared = session.get(Job, job.id)
        assert prepared is not None
        assert prepared.status == JobStatus.PREPARED
        events = session.execute(
            select(Event).where(Event.job_id == job.id)
        ).scalars().all()
        assert any(event.payload_json["new"] == "prepared" for event in events)


def test_prepare_application_missing_job(session_factory) -> None:
    """Una vacante inexistente devuelve error sin tocar el LLM."""
    result = prepare_application(job_id=9999, llm=FakeLLMClient([]))
    assert result["exito"] is False
    assert "no encontrada" in result["error"]


def test_prepare_application_extraction_failure(
    session_factory, job, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el LLM de extracción falla dos veces, se reporta el error."""
    failing = FakeLLMClient([RuntimeError("boom"), RuntimeError("boom")])
    result = prepare_application(job_id=job.id, llm=failing)
    assert result["exito"] is False
    assert "No se pudieron extraer requisitos" in result["error"]


def test_prepare_application_never_sends_gap_keywords_to_writer(
    session_factory, job, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El LLM de redacción solo ve keywords soportadas."""
    _patch_render(monkeypatch, tmp_path)
    extraction_llm = FakeLLMClient([_extraction()])
    writing_llm = FakeLLMClient([_tailored()])

    result = prepare_application(
        job_id=job.id, llm=extraction_llm, writing_llm=writing_llm
    )
    assert result["exito"] is True
    assert len(writing_llm.calls) == 1
    writer_prompt = writing_llm.calls[0]["user"]
    assert "Power BI" in writer_prompt
    assert "Excel" not in writer_prompt


def test_get_application_artifacts_none_without_application(session_factory, job) -> None:
    """Sin postulación previa devuelve None."""
    assert get_application_artifacts(job.id) is None


def test_get_application_artifacts_returns_prepared_data(
    session_factory, job, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con postulación previa devuelve tailored, keywords y knockouts."""
    _patch_render(monkeypatch, tmp_path)
    prepare_application(
        job_id=job.id,
        llm=FakeLLMClient([_extraction()]),
        writing_llm=FakeLLMClient([_tailored()]),
    )

    artifacts = get_application_artifacts(job.id)
    assert artifacts is not None
    assert artifacts["tailored"]["headline"] == "Desarrollador"
    assert [kw["term"] for kw in artifacts["keywords"]] == ["Power BI", "Excel"]
    assert artifacts["keywords"][0]["status"] == "supported"
    assert artifacts["keywords"][1]["status"] == "gap"
    assert artifacts["knockouts"][0]["status"] == "not_met"
