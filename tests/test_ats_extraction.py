"""Tests de la extracción de requisitos ATS con LLM (Fase 4A).

Usan un FakeLLMClient: sin red y sin consumo de tokens.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from jobradar.ats_keywords import (
    ATSExtraction,
    compute_description_hash,
    ensure_requirements,
    extract_requirements,
    render_extraction_prompt,
)
from jobradar.db.models import Base, Company, Job, JobRequirement, JobStatus
from jobradar.llm.base import LLMClient


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


def _extraction(**overrides: Any) -> ATSExtraction:
    """Construye una extracción válida de ejemplo."""
    payload: dict[str, Any] = {
        "job_title_exact": "Financial Analyst",
        "language": "en",
        "keywords": [
            {
                "term": "Power BI",
                "type": "tool",
                "importance": "required",
                "synonyms": ["PowerBI"],
                "frequency_in_posting": 3,
            }
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
    payload.update(overrides)
    return ATSExtraction.model_validate(payload)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """SQLite en memoria para no tocar data/jobradar.sqlite."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def job(session_factory: sessionmaker[Session]) -> Job:
    """Vacante de prueba con descripción realista."""
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
            description_text="We need 3+ years of FP&A and Power BI experience.",
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

    return record


# ---------------------------------------------------------------------------
# Prompt y validación
# ---------------------------------------------------------------------------


def test_render_prompt_replaces_description_placeholder() -> None:
    """La descripción se inserta y el placeholder desaparece."""
    prompt = render_extraction_prompt(
        "Buscamos analista", template="Reglas fijas.\n{job_description}\nFin."
    )

    assert prompt == "Reglas fijas.\nBuscamos analista\nFin."
    assert "{job_description}" not in prompt


def test_extract_returns_validated_payload() -> None:
    """Devuelve el diccionario validado con keywords y knockouts."""
    llm = FakeLLMClient([_extraction()])

    result = extract_requirements("descripción de prueba", llm=llm)

    assert result["job_title_exact"] == "Financial Analyst"
    assert result["language"] == "en"
    assert result["keywords"][0]["term"] == "Power BI"
    assert result["keywords"][0]["importance"] == "required"
    assert result["knockouts"][0]["type"] == "years_experience"
    assert llm.calls[0]["schema"] is ATSExtraction
    assert "descripción de prueba" in llm.calls[0]["user"]


def test_extract_normalizes_unexpected_enum_values() -> None:
    """Valores fuera del enum se normalizan en vez de tumbar la extracción."""
    llm = FakeLLMClient(
        [
            _extraction(
                language="EN-us",
                keywords=[
                    {"term": "Power BI", "type": "inventado", "importance": "CRITICAL"}
                ],
                knockouts=[{"type": "inventado", "requirement": "algo"}],
            )
        ]
    )

    result = extract_requirements("x", llm=llm)

    assert result["language"] == "en"
    assert result["keywords"][0]["type"] == "hard_skill"
    assert result["keywords"][0]["importance"] == "mentioned"
    assert result["knockouts"][0]["type"] == "other"


def test_extract_rejects_keyword_without_term() -> None:
    """Una keyword sin `term` es inválida."""
    with pytest.raises(ValueError):
        ATSExtraction.model_validate({"keywords": [{"term": ""}]})


def test_extract_retries_once_after_invalid_output() -> None:
    """Un fallo del LLM se reintenta una vez."""
    llm = FakeLLMClient([RuntimeError("json inválido"), _extraction()])

    result = extract_requirements("x", llm=llm)

    assert result["keywords"][0]["term"] == "Power BI"
    assert len(llm.calls) == 2


def test_extract_raises_after_all_attempts_fail() -> None:
    """Si ambos intentos fallan, se propaga RuntimeError."""
    llm = FakeLLMClient([RuntimeError("boom"), RuntimeError("boom")])

    with pytest.raises(RuntimeError, match="2 intentos"):
        extract_requirements("x", llm=llm)


def test_extract_raises_on_wrong_return_type() -> None:
    """Un cliente que no devuelve el modelo esperado falla explícitamente."""
    llm = FakeLLMClient(["texto suelto", "texto suelto"])

    with pytest.raises(RuntimeError, match="ATSExtraction"):
        extract_requirements("x", llm=llm)


def test_compute_description_hash_is_stable() -> None:
    """El hash es determinista y cambia con el texto."""
    assert compute_description_hash("abc") == compute_description_hash("abc")
    assert compute_description_hash("abc") != compute_description_hash("abd")


# ---------------------------------------------------------------------------
# Caché en job_requirements
# ---------------------------------------------------------------------------


def test_ensure_requirements_caches_by_description_hash(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """La segunda llamada sale de caché y no gasta otra llamada al LLM."""
    llm = FakeLLMClient([_extraction()])

    first = ensure_requirements(job, session_factory, llm)
    second = ensure_requirements(job, session_factory, llm)

    assert first == second
    assert len(llm.calls) == 1
    with session_factory() as session:
        assert session.query(JobRequirement).count() == 1


def test_ensure_requirements_keeps_metadata_on_cache_hit(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """La caché conserva título exacto e idioma."""
    llm = FakeLLMClient([_extraction()])

    ensure_requirements(job, session_factory, llm)
    cached = ensure_requirements(job, session_factory, llm)

    assert cached["job_title_exact"] == "Financial Analyst"
    assert cached["language"] == "en"


def test_ensure_requirements_stores_model_name(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Se registra el modelo que produjo la extracción."""
    ensure_requirements(job, session_factory, FakeLLMClient([_extraction()]))

    with session_factory() as session:
        record = session.query(JobRequirement).one()
        assert record.model == "fake-model"
        assert record.prompt_version == "ats_extract_v1"
        assert record.description_hash == compute_description_hash(job.description_text)


def test_ensure_requirements_reextracts_when_description_changes(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Si cambia la descripción, cambia el hash y se vuelve a extraer."""
    llm = FakeLLMClient([_extraction(), _extraction(job_title_exact="Otro título")])

    ensure_requirements(job, session_factory, llm)
    job.description_text = "Descripción distinta con SQL y Python."
    result = ensure_requirements(job, session_factory, llm)

    assert result["job_title_exact"] == "Otro título"
    assert len(llm.calls) == 2
    with session_factory() as session:
        assert session.query(JobRequirement).count() == 2


def test_ensure_requirements_reextracts_for_new_prompt_version(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Cambiar la versión del prompt invalida la caché."""
    llm = FakeLLMClient([_extraction(), _extraction()])

    ensure_requirements(job, session_factory, llm, prompt_version="ats_extract_v1")
    ensure_requirements(job, session_factory, llm, prompt_version="ats_extract_v2")

    assert len(llm.calls) == 2
    with session_factory() as session:
        versions = {r.prompt_version for r in session.query(JobRequirement).all()}
        assert versions == {"ats_extract_v1", "ats_extract_v2"}


def test_ensure_requirements_reads_legacy_flat_keyword_list(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Un registro antiguo con lista plana de keywords sigue funcionando."""
    with session_factory() as session:
        session.add(
            JobRequirement(
                job_id=job.id,
                description_hash=compute_description_hash(job.description_text),
                prompt_version="ats_extract_v1",
                model="modelo-antiguo",
                keywords_json=[{"term": "Excel"}],
                knockouts_json=[{"type": "language", "requirement": "inglés"}],
            )
        )
        session.commit()

    llm = FakeLLMClient([])
    result = ensure_requirements(job, session_factory, llm)

    assert result["keywords"] == [{"term": "Excel"}]
    assert result["job_title_exact"] == ""
    assert result["language"] == "es"
    assert llm.calls == []
