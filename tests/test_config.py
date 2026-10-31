"""Tests para configuración (config.py)."""

import os
import tempfile
from pathlib import Path

import pytest

from jobradar.config import (
    CompanyConfig,
    Settings,
    load_config,
)


def test_load_config_valid_yaml():
    """Test carga de config.yaml válido."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("""
search:
  keywords_include: ["analista financiero"]
  max_age_days: 14
llm:
  provider: "anthropic"
  model_scoring: "claude-3-haiku-20240307"
  max_jobs_per_run: 30
http:
  requests_per_second: 1.5
  timeout_seconds: 30
ats:
  min_required_coverage: 0.85
  max_pages: 1
companies:
  - name: "Test Corp"
    source: "greenhouse"
    slug: "testcorp"
""")

        settings = load_config(str(config_path))

        assert settings.search.keywords_include == ["analista financiero"]
        assert settings.search.max_age_days == 14
        assert settings.llm.provider == "anthropic"
        assert settings.llm.model_scoring == "claude-3-haiku-20240307"
        assert settings.llm.max_jobs_per_run == 30
        assert settings.http.requests_per_second == 1.5
        assert settings.http.timeout_seconds == 30
        assert settings.ats.min_required_coverage == 0.85
        assert settings.ats.max_pages == 1
        assert len(settings.companies) == 1
        assert settings.companies[0].name == "Test Corp"
        assert settings.companies[0].source == "greenhouse"
        assert settings.companies[0].slug == "testcorp"


def test_load_config_missing_file_uses_defaults():
    """Test que archivo faltante usa valores por defecto."""
    settings = load_config("archivo_que_no_existe.yaml")

    assert settings.search.keywords_include == []
    assert settings.search.max_age_days == 7
    assert settings.llm.provider == "anthropic"
    assert settings.llm.max_jobs_per_run == 50
    assert settings.http.requests_per_second == 1.0
    assert settings.http.timeout_seconds == 20
    assert settings.ats.min_required_coverage == 0.90
    assert settings.ats.max_pages == 2


def test_load_config_missing_field_error():
    """Test que campo obligatorio faltante da error claro."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("""
search:
  keywords_include: ["test"]
llm:
  provider: "anthropic"
# Falta company config obligatorio (name, source)
companies:
  - name: "Test"
    # source faltante
""")

        with pytest.raises(Exception) as exc_info:
            load_config(str(config_path))

        # Debe ser un error de validación de pydantic
        assert "source" in str(exc_info.value).lower() or "validation" in str(exc_info.value).lower()


def test_settings_no_api_key_in_logs():
    """Test que API keys no aparecen en repr/str del settings."""
    settings = Settings(
        anthropic_api_key="sk-ant-secret123",
        ollama_base_url="http://localhost:11434"
    )

    settings_str = str(settings)
    settings_repr = repr(settings)

    assert "secret123" not in settings_str
    assert "secret123" not in settings_repr
    assert "sk-ant" not in settings_str
    assert "sk-ant" not in settings_repr


def test_company_config_validation():
    """Test validación de CompanyConfig."""
    # Greenhouse válido
    gh = CompanyConfig(name="Test", source="greenhouse", slug="test")
    assert gh.slug == "test"

    # Lever válido
    lv = CompanyConfig(name="Test", source="lever", slug="test")
    assert lv.slug == "test"

    # Workday válido
    wd = CompanyConfig(name="Test", source="workday", tenant="test", wd=5, site="External")
    assert wd.tenant == "test"
    assert wd.wd == 5


def test_settings_env_override():
    """Test que variables de entorno sobrescriben config.yaml."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("""
llm:
  provider: "anthropic"
  model_scoring: "claude-3-haiku-20240307"
""")

        # Set env var
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-from-env"

        try:
            settings = load_config(str(config_path))
            assert settings.anthropic_api_key == "sk-ant-from-env"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
