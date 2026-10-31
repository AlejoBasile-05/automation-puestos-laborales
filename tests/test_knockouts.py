"""Tests de filtros eliminatorios (knockouts) - sin LLM, sin red."""

from jobradar.knockouts import check_knockouts

CV_MASTER_TEST_PATH = "tests/fixtures/cv_master_test.yaml"


def test_knockout_years_experience_met():
    """Años de experiencia cumplidos: met."""
    knockouts = [
        {"type": "years_experience", "requirement": "3+ años en backend", "value": 3, "area": "backend", "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "met"
    assert result[0]["evidence"] is not None


def test_knockout_years_experience_not_met():
    """Años de experiencia no cumplidos: not_met."""
    knockouts = [
        {"type": "years_experience", "requirement": "10+ años en backend", "value": 10, "area": "backend", "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "not_met"


def test_knockout_language_met():
    """Idioma cumplido: met."""
    knockouts = [
        {"type": "language", "requirement": "Inglés B2", "value": "B2", "area": None, "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "met"


def test_knockout_language_not_met():
    """Idioma no cumplido: not_met."""
    knockouts = [
        {"type": "language", "requirement": "Alemán C1", "value": "C1", "area": None, "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "not_met"


def test_knockout_unknown_when_uncertain():
    """Ante la duda: unknown."""
    knockouts = [
        {"type": "other", "requirement": "Disponibilidad para viajar", "value": None, "area": None, "mandatory": False}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "unknown"


def test_knockout_work_authorization_met():
    """Autorización de trabajo cumplida: met."""
    knockouts = [
        {"type": "work_authorization", "requirement": "Autorizado para trabajar en Argentina", "value": "Argentina", "area": None, "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "met"


def test_knockout_work_authorization_not_met():
    """Autorización de trabajo no cumplida: not_met."""
    knockouts = [
        {"type": "work_authorization", "requirement": "Autorizado para trabajar en USA", "value": "USA", "area": None, "mandatory": True}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "not_met"


def test_knockout_never_assumes_met():
    """Nunca asume que se cumple: unknown por defecto para casos no determinísticos."""
    knockouts = [
        {"type": "certification", "requirement": "AWS Certified", "value": None, "area": None, "mandatory": False}
    ]
    result = check_knockouts(knockouts, CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "unknown"
