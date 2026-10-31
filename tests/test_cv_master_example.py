"""Tests para examples/cv_master.example.yaml."""

from pathlib import Path

import pytest
import yaml


def load_cv_master() -> dict:
    """Carga el CV maestro de ejemplo."""
    path = Path("examples/cv_master.example.yaml")
    assert path.exists(), f"No existe {path}"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_cv_master_loads():
    """Test que el YAML carga sin errores."""
    cv = load_cv_master()
    assert cv is not None
    assert isinstance(cv, dict)


def test_cv_master_has_required_sections():
    """Test que tiene todas las secciones requeridas del esquema sección 7."""
    cv = load_cv_master()

    required_sections = [
        "basics", "summary_facts", "target_titles", "eligibility",
        "experience", "education", "skills", "certifications", "languages"
    ]

    for section in required_sections:
        assert section in cv, f"Falta sección requerida: {section}"


def test_basics_has_required_fields():
    """Test que basics tiene campos obligatorios."""
    cv = load_cv_master()
    basics = cv["basics"]

    assert "name" in basics and basics["name"]
    assert "email" in basics and basics["email"]
    assert "phone" in basics and basics["phone"]
    assert "location" in basics and basics["location"]
    assert "links" in basics and isinstance(basics["links"], list)


def test_experience_has_ids_and_bullets():
    """Test que experience tiene ids y bullets con ids."""
    cv = load_cv_master()
    experience = cv["experience"]

    assert isinstance(experience, list)
    assert len(experience) > 0

    for exp in experience:
        assert "id" in exp and exp["id"], "Experience debe tener id"
        assert "company" in exp and exp["company"]
        assert "title" in exp and exp["title"]
        assert "start" in exp and exp["start"]
        assert "end" in exp and exp["end"]
        assert "location" in exp and exp["location"]
        assert "bullets" in exp and isinstance(exp["bullets"], list)

        for bullet in exp["bullets"]:
            assert "id" in bullet and bullet["id"], "Bullet debe tener id"
            assert "text" in bullet and bullet["text"]
            assert "tags" in bullet and isinstance(bullet["tags"], list)


def test_education_has_ids():
    """Test que education tiene ids."""
    cv = load_cv_master()
    education = cv["education"]

    assert isinstance(education, list)
    assert len(education) > 0

    for edu in education:
        assert "id" in edu and edu["id"], "Education debe tener id"
        assert "institution" in edu and edu["institution"]
        assert "degree" in edu and edu["degree"]
        assert "year" in edu and edu["year"]


def test_skills_has_aliases_and_years():
    """Test que skills tiene aliases, years, level, tags."""
    cv = load_cv_master()
    skills = cv["skills"]

    assert isinstance(skills, list)
    assert len(skills) > 0

    for skill in skills:
        assert "name" in skill and skill["name"]
        assert "aliases" in skill and isinstance(skill["aliases"], list)
        assert "tags" in skill and isinstance(skill["tags"], list)
        assert "level" in skill and skill["level"]
        assert "years" in skill and isinstance(skill["years"], int) and skill["years"] >= 0


def test_eligibility_structure():
    """Test que eligibility tiene la estructura correcta."""
    cv = load_cv_master()
    eligibility = cv["eligibility"]

    assert "years_experience" in eligibility
    yoe = eligibility["years_experience"]
    assert "total" in yoe and isinstance(yoe["total"], int)
    assert "by_area" in yoe and isinstance(yoe["by_area"], dict)

    assert "work_authorization" in eligibility and isinstance(eligibility["work_authorization"], list)
    assert "relocation" in eligibility and isinstance(eligibility["relocation"], bool)
    assert "remote_ok" in eligibility and isinstance(eligibility["remote_ok"], bool)


def test_all_ids_unique():
    """Test que TODOS los IDs son únicos en todo el CV."""
    cv = load_cv_master()
    all_ids = []

    # Experience IDs
    for exp in cv["experience"]:
        all_ids.append(exp["id"])
        for bullet in exp["bullets"]:
            all_ids.append(bullet["id"])

    # Education IDs
    for edu in cv["education"]:
        all_ids.append(edu["id"])

    # Verificar unicidad
    unique_ids = set(all_ids)
    assert len(all_ids) == len(unique_ids), f"IDs duplicados encontrados: {len(all_ids)} total vs {len(unique_ids)} únicos"

    # Verificar que no hay IDs vacíos
    for id_ in all_ids:
        assert id_, "ID vacío encontrado"


def test_no_real_pii():
    """Test que no hay datos personales reales (solo ficticios)."""
    cv = load_cv_master()

    # El email debe ser claramente de ejemplo
    email = cv["basics"]["email"]
    assert "ejemplo" in email.lower() or "example" in email.lower() or "test" in email.lower()

    # El nombre contiene apellidos comunes de ejemplo
    name = cv["basics"]["name"].lower()
    # Normalizar acentos para la comprobación
    import unicodedata
    name_norm = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    assert "ejemplo" in name_norm or "example" in name_norm or "test" in name_norm or "perez" in name_norm or "garcia" in name_norm

    # Teléfono con patrón de ejemplo
    phone = cv["basics"]["phone"]
    assert "1234" in phone or "5678" in phone or "0000" in phone


def test_target_titles_not_empty():
    """Test que target_titles no está vacío."""
    cv = load_cv_master()
    assert cv["target_titles"]
    assert len(cv["target_titles"]) > 0


def test_languages_have_level():
    """Test que idiomas tienen nivel."""
    cv = load_cv_master()
    languages = cv["languages"]

    assert isinstance(languages, list)
    assert len(languages) > 0

    for lang in languages:
        assert "name" in lang and lang["name"]
        assert "level" in lang and lang["level"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
