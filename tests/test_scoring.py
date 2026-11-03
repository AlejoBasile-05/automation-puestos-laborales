"""Tests del scoring de compatibilidad con LLM (Fase 3).

Usan un FakeLLMClient: sin red y sin consumo de tokens. La carga del CV
maestro y del prompt se monkeypatchea para no depender del cwd.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import jobradar.scoring as scoring
from jobradar.db.models import Base, Company, Job, JobStatus, Score
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


CV_TEXT = "CV MAESTRO FALSO"
PROMPT_TEMPLATE = (
    "CV: {cv_master}\n"
    "TITULO: {job_title}\n"
    "DESCRIPCION: {job_description}\n"
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Fábrica de sesiones sobre SQLite en memoria."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def job(session_factory: sessionmaker[Session]) -> Job:
    """Vacante persistida lista para puntuar."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_factory() as session:
        company = Company(name="Acme", source="greenhouse", slug="acme", config_json={})
        session.add(company)
        session.flush()
        job = Job(
            company_id=company.id,
            source="greenhouse",
            external_id="gh-1",
            title="Senior Python Engineer",
            location="Remote",
            description_text="Build APIs with Python.",
            url="https://example.test/gh-1",
            first_seen_at=now,
            last_seen_at=now,
            is_open=True,
            status=JobStatus.NEW,
            raw_json={},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


@pytest.fixture(autouse=True)
def _patch_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita leer archivos reales durante los tests."""
    monkeypatch.setattr(scoring, "_load_cv_master", lambda: CV_TEXT)
    monkeypatch.setattr(scoring, "_load_prompt", lambda: PROMPT_TEMPLATE)


def _score_output(**overrides: Any) -> scoring.ScoreOutput:
    payload: dict[str, Any] = {
        "score": 82,
        "verdict": "aplicar",
        "matches": ["Python"],
        "gaps": [],
        "red_flags": [],
        "language": "en",
    }
    payload.update(overrides)
    return scoring.ScoreOutput(**payload)


def test_score_job_cached_skips_llm(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Si ya existe el score con el mismo hash y versión, no llama al LLM."""
    with session_factory() as session:
        session.add(
            Score(
                job_id=job.id,
                cv_hash="hash-fijo",
                prompt_version="scoring_v1",
                model="fake-model",
                score=70,
                verdict="quizá",
                matches_json=[],
                gaps_json=[],
                red_flags_json=[],
            )
        )
        session.commit()

    llm = FakeLLMClient([])
    result = scoring.score_job(job, "hash-fijo", "scoring_v1", llm, session_factory)

    assert result == "cached"
    assert llm.calls == []


def test_score_job_scored_persists_row(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Sin caché, llama al LLM una vez y guarda el score en la base."""
    llm = FakeLLMClient([_score_output()])

    result = scoring.score_job(job, "hash-nuevo", "scoring_v1", llm, session_factory)

    assert result == "scored"
    assert len(llm.calls) == 1
    prompt = llm.calls[0]["user"]
    assert "Senior Python Engineer" in prompt
    assert "Build APIs with Python." in prompt
    assert CV_TEXT in prompt

    with session_factory() as session:
        stored = session.scalars(select(Score).where(Score.job_id == job.id)).one()
        assert stored.score == 82
        assert stored.verdict == "aplicar"
        assert stored.matches_json == ["Python"]
        assert stored.model == "fake-model"


def test_score_job_different_prompt_version_is_not_cached(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Una versión de prompt distinta invalida la caché."""
    with session_factory() as session:
        session.add(
            Score(
                job_id=job.id,
                cv_hash="hash-fijo",
                prompt_version="scoring_v0",
                model="fake-model",
                score=50,
                verdict="quizá",
                matches_json=[],
                gaps_json=[],
                red_flags_json=[],
            )
        )
        session.commit()

    llm = FakeLLMClient([_score_output(score=91)])
    result = scoring.score_job(job, "hash-fijo", "scoring_v1", llm, session_factory)

    assert result == "scored"
    with session_factory() as session:
        versions = set(session.scalars(select(Score.prompt_version)))
        assert versions == {"scoring_v0", "scoring_v1"}


def test_score_job_rejects_non_schema_result(
    session_factory: sessionmaker[Session], job: Job
) -> None:
    """Si el LLM devuelve algo que no es ScoreOutput, lanza TypeError y no persiste."""
    llm = FakeLLMClient([{"score": 80}])

    with pytest.raises(TypeError):
        scoring.score_job(job, "hash-x", "scoring_v1", llm, session_factory)

    with session_factory() as session:
        assert session.scalars(select(Score)).first() is None


def test_score_output_validates_bounds() -> None:
    """El esquema rechaza puntajes fuera de 0-100."""
    with pytest.raises(ValidationError):
        _score_output(score=101)
    with pytest.raises(ValidationError):
        _score_output(score=-1)


def test_compute_cv_hash_is_stable_and_distinct() -> None:
    """El hash es determinista y cambia con el contenido."""
    first = scoring._compute_cv_hash("contenido A")
    assert first == scoring._compute_cv_hash("contenido A")
    assert first != scoring._compute_cv_hash("contenido B")
    assert len(first) == 64


def test_resolve_run_limit_uses_configured_when_omitted() -> None:
    """Sin --limit se usa el tope de config.yaml."""
    assert scoring.resolve_run_limit(None, 50) == 50


def test_resolve_run_limit_clamps_above_configured() -> None:
    """Un límite mayor al configurado se recorta."""
    assert scoring.resolve_run_limit(1000, 50) == 50


def test_resolve_run_limit_keeps_lower_value() -> None:
    """Un límite menor al configurado se respeta."""
    assert scoring.resolve_run_limit(10, 50) == 10


def test_resolve_run_limit_never_negative() -> None:
    """Valores negativos se normalizan a cero."""
    assert scoring.resolve_run_limit(-5, 50) == 0
    assert scoring.resolve_run_limit(None, -1) == 0


def test_estimate_text_tokens() -> None:
    """La estimación de tokens usa ~4 caracteres por token."""
    assert scoring.estimate_text_tokens("") == 0
    assert scoring.estimate_text_tokens("abcd") == 1
    assert scoring.estimate_text_tokens("a" * 400) == 100


def test_estimate_cost_usd() -> None:
    """El costo suma entrada y salida según el precio por 1.000 tokens."""
    assert scoring.estimate_cost_usd(1000, 1000, 2.0, 4.0) == 6.0
    assert scoring.estimate_cost_usd(0, 0, 2.0, 4.0) == 0.0
