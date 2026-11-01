"""Tests de los prompts empaquetados y su resolución independiente del cwd."""

from pathlib import Path

import pytest

import jobradar.ats_keywords as ats_keywords
import jobradar.scoring as scoring
import jobradar.tailoring as tailoring
from jobradar.paths import PROMPTS_DIR, prompt_path

PROMPTS: dict[str, list[str]] = {
    "ats_extract_v1.md": ["{job_description}"],
    "scoring_v1.md": ["{cv_master}", "{job_title}", "{job_description}"],
    "tailoring_v1.md": ["{{keywords_supported}}"],
}


@pytest.mark.parametrize(("name", "placeholders"), PROMPTS.items())
def test_prompt_files_exist_and_keep_placeholders(
    name: str, placeholders: list[str]
) -> None:
    """Cada plantilla vive en el paquete y conserva sus placeholders."""
    path = prompt_path(name)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.strip()
    for placeholder in placeholders:
        assert placeholder in text


def test_module_prompt_paths_point_inside_package() -> None:
    """Los tres módulos resuelven sus prompts dentro del paquete."""
    for module in (ats_keywords, scoring, tailoring):
        assert module.PROMPT_PATH.is_relative_to(PROMPTS_DIR)


def test_prompts_load_independently_of_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cargar los prompts funciona aunque el proceso corra en otro directorio."""
    monkeypatch.chdir(tmp_path)

    assert "{job_description}" in ats_keywords.load_extraction_prompt()
    assert "{cv_master}" in scoring._load_prompt()
    assert "{{keywords_supported}}" in tailoring._load_prompt()


def test_render_extraction_prompt_works_from_other_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La sustitución del placeholder no depende del cwd."""
    monkeypatch.chdir(tmp_path)

    rendered = ats_keywords.render_extraction_prompt("Buscamos analista")

    assert "Buscamos analista" in rendered
    assert "{job_description}" not in rendered
