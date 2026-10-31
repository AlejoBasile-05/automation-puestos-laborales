"""Tests de matching determinista de keywords ATS (sin LLM, sin red)."""

from jobradar.ats_keywords import match_keywords, normalize_text

CV_MASTER_TEST_PATH = "tests/fixtures/cv_master_test.yaml"


def test_normalize_minusculas():
    """La normalización convierte a minúsculas."""
    assert normalize_text("HOLA Mundo") == "hola mundo"


def test_normalize_sin_acentos():
    """La normalización quita acentos."""
    assert normalize_text("Inglés") == "ingles"
    assert normalize_text("planeación") == "planeacion"


def test_normalize_sin_puntuacion():
    """La normalización quita puntuación."""
    assert normalize_text("Node.js") == "node js"
    assert normalize_text("FP&A") == "fp a"


def test_matching_powerbi_alias():
    """PowerBI debe matchear con Power BI del CV maestro (alias)."""
    result = match_keywords([{"term": "PowerBI", "type": "tool", "importance": "required"}], CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "supported"
    assert "exp_test_1" in result[0]["evidence_ids"]


def test_matching_fp_and_a_with_synonyms():
    """FP&A con sinónimo 'planeación y análisis financiero' debe matchear."""
    result = match_keywords(
        [{"term": "FP&A", "type": "hard_skill", "importance": "required", "synonyms": ["planeación y análisis financiero"]}],
        CV_MASTER_TEST_PATH,
    )
    assert len(result) == 1
    assert result[0]["status"] == "supported"
    assert "exp_test_1" in result[0]["evidence_ids"]


def test_matching_java_no_javascript():
    """Java NO debe coincidir con JavaScript (límites de palabra)."""
    result = match_keywords([{"term": "Java", "type": "hard_skill", "importance": "required"}], CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "gap"
    assert result[0]["evidence_ids"] == []


def test_matching_acentos_mayusculas():
    """INGLÉS con acento y mayúscula debe matchear con ingles."""
    result = match_keywords([{"term": "INGLÉS", "type": "language", "importance": "required"}], CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "supported"


def test_matching_plural_singular():
    """años (plural) debe matchear con años en el texto del bullet."""
    result = match_keywords([{"term": "años", "type": "hard_skill", "importance": "required"}], CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "supported"
    assert "exp_test_1" in result[0]["evidence_ids"]


def test_matching_keyword_no_en_cv():
    """Keyword no presente en el CV debe ser gap."""
    result = match_keywords([{"term": "Ruby on Rails", "type": "hard_skill", "importance": "required"}], CV_MASTER_TEST_PATH)
    assert len(result) == 1
    assert result[0]["status"] == "gap"
    assert result[0]["evidence_ids"] == []


def test_matching_multiple_keywords():
    """Varias keywords: algunas supported, otras gap."""
    keywords = [
        {"term": "PowerBI", "type": "tool", "importance": "required"},
        {"term": "Ruby", "type": "hard_skill", "importance": "required"},
        {"term": "JavaScript", "type": "hard_skill", "importance": "required"},
    ]
    result = match_keywords(keywords, CV_MASTER_TEST_PATH)
    assert len(result) == 3
    statuses = {r["term"]: r["status"] for r in result}
    assert statuses["PowerBI"] == "supported"
    assert statuses["Ruby"] == "gap"
    assert statuses["JavaScript"] == "supported"
