"""Tests de la capa de consultas del dashboard (AGENTS.md §12).

Usan SQLite en memoria: no hay red ni escritura en data/.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import jobradar.dashboard_queries as dq
from jobradar.db.models import (
    Application,
    Base,
    Company,
    Event,
    Job,
    JobStatus,
    Score,
    WorkplaceType,
)


def _naive_now() -> datetime:
    """Fecha actual sin zona, como la guarda SQLite."""
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
def session_factory(monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    """Fábrica de sesiones sobre SQLite en memoria inyectada en el módulo."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(dq, "_session_factory_override", factory)
    return factory


@pytest.fixture
def seeded(session_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Carga tres vacantes con estados, fuentes y fechas distintas."""
    now = _naive_now()
    with session_factory() as session:
        acme = Company(name="Acme", source="greenhouse", slug="acme", config_json={})
        globex = Company(name="Globex", source="lever", slug="globex", config_json={})
        session.add_all([acme, globex])
        session.flush()

        session.add_all(
            [
                Job(
                    company_id=acme.id,
                    source="greenhouse",
                    external_id="gh-1",
                    title="Senior Python Engineer",
                    location="Remote",
                    workplace_type=WorkplaceType.REMOTE,
                    department="Engineering",
                    description_text="Build APIs with Python and SQL.",
                    url="https://example.test/gh-1",
                    posted_at=now,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_open=True,
                    status=JobStatus.NEW,
                    raw_json={},
                ),
                Job(
                    company_id=globex.id,
                    source="lever",
                    external_id="lv-2",
                    title="Data Analyst",
                    location="Monterrey",
                    workplace_type=WorkplaceType.ONSITE,
                    department="Data",
                    description_text="Dashboards and reporting.",
                    url="https://example.test/lv-2",
                    posted_at=now - timedelta(days=10),
                    first_seen_at=now - timedelta(days=10),
                    last_seen_at=now,
                    is_open=True,
                    status=JobStatus.APPLIED,
                    raw_json={},
                ),
                Job(
                    company_id=acme.id,
                    source="greenhouse",
                    external_id="gh-3",
                    title="Old Closed Role",
                    location=None,
                    workplace_type=None,
                    department=None,
                    description_text="Legacy role.",
                    url="https://example.test/gh-3",
                    posted_at=now - timedelta(days=60),
                    first_seen_at=now - timedelta(days=60),
                    last_seen_at=now - timedelta(days=30),
                    is_open=False,
                    status=JobStatus.DISCARDED,
                    raw_json={},
                ),
            ]
        )

        applied_job = session.query(Job).filter_by(external_id="lv-2").one()
        session.add(
            Application(
                job_id=applied_job.id,
                tailored_cv_json={},
                message_text="Hola",
                language="es",
                required_coverage=0.9,
                applied_at=now - timedelta(days=10),
                notes="Seguimiento pendiente",
            )
        )
        session.add(
            Event(
                job_id=applied_job.id,
                type="status_change",
                payload_json={"old": "new", "new": "applied"},
            )
        )
        session.commit()

    return session_factory


def _titles(jobs: list[Job]) -> list[str]:
    return [job.title for job in jobs]


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------


def test_get_filtered_jobs_without_filters(seeded: sessionmaker[Session]) -> None:
    """Sin filtros devuelve todas las vacantes."""
    assert len(dq.get_filtered_jobs()) == 3


def test_get_filtered_jobs_only_open(seeded: sessionmaker[Session]) -> None:
    """only_open excluye las cerradas."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(only_open=True))
    assert _titles(jobs) == ["Senior Python Engineer", "Data Analyst"]


def test_get_filtered_jobs_by_source(seeded: sessionmaker[Session]) -> None:
    """Filtra por fuente, sin importar mayúsculas."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(source="LEVER"))
    assert _titles(jobs) == ["Data Analyst"]


def test_get_filtered_jobs_by_search_text(seeded: sessionmaker[Session]) -> None:
    """Busca en título y descripción."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(search_text="python"))
    assert _titles(jobs) == ["Senior Python Engineer"]

    by_description = dq.get_filtered_jobs(dq.JobFilters(search_text="dashboards"))
    assert _titles(by_description) == ["Data Analyst"]


def test_get_filtered_jobs_by_company(seeded: sessionmaker[Session]) -> None:
    """Filtra por nombre de empresa."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(company="acme"))
    assert _titles(jobs) == ["Senior Python Engineer", "Old Closed Role"]


def test_get_filtered_jobs_by_location(seeded: sessionmaker[Session]) -> None:
    """Filtra por ubicación."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(location="monterrey"))
    assert _titles(jobs) == ["Data Analyst"]


def test_get_filtered_jobs_remote_only(seeded: sessionmaker[Session]) -> None:
    """El filtro remoto usa workplace_type."""
    jobs = dq.get_filtered_jobs(dq.JobFilters(remote=True))
    assert _titles(jobs) == ["Senior Python Engineer"]


def test_get_filtered_jobs_date_range(seeded: sessionmaker[Session]) -> None:
    """Filtra por rango de fechas de publicación."""
    today = datetime.now(UTC).date()
    recent = dq.get_filtered_jobs(
        dq.JobFilters(date_from=today - timedelta(days=5))
    )
    assert _titles(recent) == ["Senior Python Engineer"]

    older = dq.get_filtered_jobs(dq.JobFilters(date_to=today - timedelta(days=5)))
    assert _titles(older) == ["Data Analyst", "Old Closed Role"]


def test_get_filtered_jobs_by_status(seeded: sessionmaker[Session]) -> None:
    """Filtra por estado y ignora estados inválidos."""
    assert _titles(dq.get_filtered_jobs(dq.JobFilters(status="applied"))) == [
        "Data Analyst"
    ]
    assert len(dq.get_filtered_jobs(dq.JobFilters(status="inventado"))) == 3


def test_get_filtered_jobs_marks_new(seeded: sessionmaker[Session]) -> None:
    """Marca is_new solo para vacantes publicadas tras la última visita."""
    last_visit = _naive_now() - timedelta(days=2)
    jobs = dq.get_filtered_jobs(last_visit=last_visit)
    flags = {job.title: job.is_new for job in jobs}
    assert flags["Senior Python Engineer"] is True
    assert flags["Data Analyst"] is False
    assert flags["Old Closed Role"] is False


# ---------------------------------------------------------------------------
# Detalle y eventos
# ---------------------------------------------------------------------------


def test_get_job_details(seeded: sessionmaker[Session]) -> None:
    """Devuelve la vacante con su empresa cargada."""
    job = dq.get_job_details(1)
    assert job is not None
    assert job.title == "Senior Python Engineer"
    assert job.company is not None
    assert job.company.name == "Acme"


def test_get_job_details_missing(seeded: sessionmaker[Session]) -> None:
    """Devuelve None si la vacante no existe."""
    assert dq.get_job_details(9999) is None


def test_get_job_events(seeded: sessionmaker[Session]) -> None:
    """Devuelve los eventos de la vacante."""
    events = dq.get_job_events(2)
    assert len(events) == 1
    assert events[0].type == "status_change"
    assert events[0].payload_json["new"] == "applied"


# ---------------------------------------------------------------------------
# Cambios de estado
# ---------------------------------------------------------------------------


def test_mark_job_reviewed_creates_event(seeded: sessionmaker[Session]) -> None:
    """Cambia el estado y registra el evento old/new."""
    dq.mark_job_reviewed(1)
    job = dq.get_job_details(1)
    assert job is not None
    assert job.status == JobStatus.REVIEWED

    events = dq.get_job_events(1)
    assert len(events) == 1
    assert events[0].payload_json == {"old": "new", "new": "reviewed"}


def test_mark_job_discarded_creates_event(seeded: sessionmaker[Session]) -> None:
    """Cambia el estado a descartada y registra el evento."""
    dq.mark_job_discarded(1)
    job = dq.get_job_details(1)
    assert job is not None
    assert job.status == JobStatus.DISCARDED
    assert dq.get_job_events(1)[0].payload_json["new"] == "discarded"


def test_mark_job_reviewed_missing_raises(seeded: sessionmaker[Session]) -> None:
    """Un ID inexistente lanza ValueError."""
    with pytest.raises(ValueError, match="no encontrada"):
        dq.mark_job_reviewed(9999)


def test_mark_job_applied_creates_application(seeded: sessionmaker[Session]) -> None:
    """Crea la postulación, marca el estado y registra el evento."""
    dq.mark_job_applied(1)

    job = dq.get_job_details(1)
    assert job is not None
    assert job.status == JobStatus.APPLIED
    assert dq.get_job_events(1)[0].payload_json["new"] == "applied"

    with seeded() as session:
        application = (
            session.query(Application).filter_by(job_id=1).one_or_none()
        )
        assert application is not None
        assert application.applied_at is not None


def test_mark_job_applied_twice_raises(seeded: sessionmaker[Session]) -> None:
    """No permite duplicar la postulación de la misma vacante."""
    dq.mark_job_applied(1)
    with pytest.raises(ValueError, match="Ya existe una aplicación"):
        dq.mark_job_applied(1)


def test_mark_job_applied_existing_application_raises(
    seeded: sessionmaker[Session],
) -> None:
    """Una postulación ya registrada bloquea la acción."""
    with pytest.raises(ValueError, match="Ya existe una aplicación"):
        dq.mark_job_applied(2)


# ---------------------------------------------------------------------------
# Notas
# ---------------------------------------------------------------------------


def test_get_application_notes(seeded: sessionmaker[Session]) -> None:
    """Devuelve las notas existentes y cadena vacía si no hay postulación."""
    assert dq.get_application_notes(2) == "Seguimiento pendiente"
    assert dq.get_application_notes(1) == ""


def test_set_application_notes_creates_application(
    seeded: sessionmaker[Session],
) -> None:
    """Si no existe postulación, la crea al guardar notas."""
    dq.set_application_notes(1, "Llamar el lunes")
    assert dq.get_application_notes(1) == "Llamar el lunes"


def test_set_application_notes_updates_existing(
    seeded: sessionmaker[Session],
) -> None:
    """Actualiza las notas de una postulación existente."""
    dq.set_application_notes(2, "Ya respondieron")
    assert dq.get_application_notes(2) == "Ya respondieron"


def test_set_application_notes_ignores_empty_without_application(
    seeded: sessionmaker[Session],
) -> None:
    """No crea postulaciones vacías."""
    dq.set_application_notes(1, "   ")
    with seeded() as session:
        assert session.query(Application).filter_by(job_id=1).count() == 0


# ---------------------------------------------------------------------------
# Seguimiento y exportación
# ---------------------------------------------------------------------------


def test_get_jobs_by_status(seeded: sessionmaker[Session]) -> None:
    """Cuenta vacantes por estado."""
    assert dq.get_jobs_by_status() == {"new": 1, "applied": 1, "discarded": 1}


def test_get_all_jobs_with_status(seeded: sessionmaker[Session]) -> None:
    """Lista vacantes con estado, empresa y fechas."""
    rows = dq.get_all_jobs_with_status()
    assert len(rows) == 3
    assert {row["company"] for row in rows} == {"Acme", "Globex"}

    applied = dq.get_all_jobs_with_status("applied")
    assert len(applied) == 1
    assert applied[0]["title"] == "Data Analyst"
    assert applied[0]["applied_at"] is not None
    assert applied[0]["notes"] == "Seguimiento pendiente"


def test_get_all_jobs_with_status_ignores_invalid_status(
    seeded: sessionmaker[Session],
) -> None:
    """Un estado inválido no filtra nada."""
    assert len(dq.get_all_jobs_with_status("inventado")) == 3


def test_get_jobs_without_response(seeded: sessionmaker[Session]) -> None:
    """Detecta postulaciones antiguas sin respuesta."""
    pending = dq.get_jobs_without_response(days=7)
    assert len(pending) == 1
    assert pending[0]["title"] == "Data Analyst"
    assert pending[0]["applied_at"] is not None

    assert dq.get_jobs_without_response(days=30) == []


def test_export_jobs_to_csv(seeded: sessionmaker[Session]) -> None:
    """Exporta cabecera y filas con los datos de seguimiento."""
    csv_text = dq.export_jobs_to_csv()
    lines = csv_text.strip().splitlines()

    assert lines[0] == (
        "job_id,titulo,empresa,fuente,estado,fecha_publicacion,"
        "fecha_aplicacion,notas"
    )
    assert len(lines) == 4
    assert "Senior Python Engineer" in csv_text
    assert "Seguimiento pendiente" in csv_text


# ---------------------------------------------------------------------------
# Última visita
# ---------------------------------------------------------------------------


def test_last_visit_roundtrip(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda y recupera la marca de la última visita."""
    monkeypatch.setattr(dq, "LAST_VISIT_FILE", tmp_path / "last_visit.json")

    assert dq.get_last_visit() is None

    timestamp = datetime(2026, 10, 31, 12, 0, 0)
    dq.set_last_visit(timestamp)
    assert dq.get_last_visit() == timestamp


def test_last_visit_empty_file_returns_none(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un archivo vacío no rompe la lectura."""
    visit_file = tmp_path / "last_visit.json"
    visit_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(dq, "LAST_VISIT_FILE", visit_file)

    assert dq.get_last_visit() is None


# ---------------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------------


def test_run_ingest_uses_configured_companies(
    seeded: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La ingesta recibe la fábrica de sesiones inyectada."""
    captured: dict[str, object] = {}

    def fake_ingest(companies, session_factory=None):
        from jobradar.ingest import IngestSummary

        captured["companies"] = companies
        captured["session_factory"] = session_factory
        return IngestSummary(companies_processed=len(companies), jobs_new=7)

    monkeypatch.setattr(dq, "ingest_companies", fake_ingest)
    result = dq.run_ingest()

    assert result.jobs_new == 7
    assert captured["session_factory"] is seeded


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_get_scores_for_jobs_returns_latest_per_job(
    seeded: sessionmaker[Session],
) -> None:
    """Devuelve el score más reciente de cada vacante en una sola consulta."""
    base = _naive_now()
    with seeded() as session:
        job = session.query(Job).filter_by(external_id="gh-1").one()
        job_id = job.id
        session.add_all(
            [
                Score(
                    job_id=job_id,
                    cv_hash="viejo",
                    prompt_version="scoring_v0",
                    model="fake-model",
                    score=40,
                    verdict="quizá",
                    matches_json=[],
                    gaps_json=[],
                    red_flags_json=[],
                    created_at=base - timedelta(minutes=5),
                ),
                Score(
                    job_id=job_id,
                    cv_hash="nuevo",
                    prompt_version="scoring_v1",
                    model="fake-model",
                    score=88,
                    verdict="aplicar",
                    matches_json=["Python"],
                    gaps_json=["Go"],
                    red_flags_json=["sin salario"],
                    created_at=base,
                ),
            ]
        )
        session.commit()

    result = dq.get_scores_for_jobs([job_id])

    assert set(result) == {job_id}
    assert result[job_id]["score"] == 88
    assert result[job_id]["verdict"] == "aplicar"
    assert result[job_id]["matches"] == ["Python"]
    assert result[job_id]["gaps"] == ["Go"]
    assert result[job_id]["red_flags"] == ["sin salario"]
    assert result[job_id]["model"] == "fake-model"


def test_get_scores_for_jobs_empty_input_returns_empty() -> None:
    """Sin IDs no se consulta la base."""
    assert dq.get_scores_for_jobs([]) == {}


def test_run_scoring_delegates_with_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El wrapper del dashboard pasa el límite a score_pending."""
    captured: dict[str, object] = {}

    def fake_score_pending(limit: int | None = None) -> dict[str, object]:
        captured["limit"] = limit
        return {
            "scored": 0,
            "cached": 0,
            "errors": 0,
            "total": 0,
            "limit": limit,
        }

    monkeypatch.setattr(dq, "score_pending", fake_score_pending)

    result = dq.run_scoring(limit=3)

    assert captured["limit"] == 3
    assert result["limit"] == 3


def test_get_filtered_jobs_min_score_excludes_unscored(
    seeded: sessionmaker[Session],
) -> None:
    """Con puntaje mínimo solo quedan vacantes con score vigente >= umbral."""
    base = _naive_now()
    with seeded() as session:
        job = session.query(Job).filter_by(external_id="gh-1").one()
        session.add(
            Score(
                job_id=job.id,
                cv_hash="h",
                prompt_version="scoring_v1",
                model="fake-model",
                score=80,
                verdict="aplicar",
                matches_json=[],
                gaps_json=[],
                red_flags_json=[],
                created_at=base,
            )
        )
        session.commit()

    jobs = dq.get_filtered_jobs(dq.JobFilters(min_score=70))

    assert [job.external_id for job in jobs] == ["gh-1"]


def test_get_filtered_jobs_sort_by_score_orders_descending(
    seeded: sessionmaker[Session],
) -> None:
    """Ordenar por puntaje deja primero el más alto y al final los sin score."""
    base = _naive_now()
    with seeded() as session:
        gh1 = session.query(Job).filter_by(external_id="gh-1").one()
        lv2 = session.query(Job).filter_by(external_id="lv-2").one()
        session.add_all(
            [
                Score(
                    job_id=gh1.id,
                    cv_hash="a",
                    prompt_version="scoring_v1",
                    model="m",
                    score=80,
                    verdict="aplicar",
                    matches_json=[],
                    gaps_json=[],
                    red_flags_json=[],
                    created_at=base,
                ),
                Score(
                    job_id=lv2.id,
                    cv_hash="b",
                    prompt_version="scoring_v1",
                    model="m",
                    score=95,
                    verdict="aplicar",
                    matches_json=[],
                    gaps_json=[],
                    red_flags_json=[],
                    created_at=base,
                ),
            ]
        )
        session.commit()

    jobs = dq.get_filtered_jobs(dq.JobFilters(), sort="puntaje")

    assert [job.external_id for job in jobs] == ["lv-2", "gh-1", "gh-3"]
