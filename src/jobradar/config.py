"""Configuración: carga y valida config.yaml + .env con pydantic v2."""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SearchConfig(BaseModel):
    """Configuración de búsqueda y filtros."""
    keywords_include: list[str] = Field(default_factory=list)
    keywords_exclude: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    accept_remote: bool = True
    max_age_days: int = 7


class LLMConfig(BaseModel):
    """Configuración del proveedor LLM."""
    provider: str = "anthropic"  # anthropic | ollama | nvidia
    model_scoring: str = "claude-3-haiku-20240307"
    model_writing: str = "claude-3-5-sonnet-20241022"
    max_jobs_per_run: int = 50
    # Precio opcional por 1.000 tokens para estimar costo antes de ejecutar (0 = sin precio).
    price_input_per_1k_usd: float = 0.0
    price_output_per_1k_usd: float = 0.0


class HTTPConfig(BaseModel):
    """Configuración HTTP."""
    requests_per_second: float = 1.0
    timeout_seconds: int = 20


class ATSConfig(BaseModel):
    """Configuración ATS."""
    min_required_coverage: float = 0.90
    max_keyword_repetitions: int = 3
    max_pages: int = 2
    font: str = "Arial"
    font_size_pt: int = 11
    date_format: str = "MMM YYYY"


class DiscoveryConfig(BaseModel):
    """Configuración del descubrimiento de empresas (Fase 7)."""
    provider: str = "brave"  # brave | google_cse
    max_queries_per_run: int = 5
    cache_ttl_hours: int = 24


class CompanyConfig(BaseModel):
    """Configuración de una empresa objetivo."""
    name: str
    source: str  # greenhouse | lever | ashby | workday
    slug: str | None = None
    tenant: str | None = None
    wd: int | None = None
    site: str | None = None


class Settings(BaseSettings):
    """Configuración principal de la aplicación."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    search: SearchConfig = Field(default_factory=SearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    http: HTTPConfig = Field(default_factory=HTTPConfig)
    ats: ATSConfig = Field(default_factory=ATSConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    companies: list[CompanyConfig] = Field(default_factory=list)

    # Secrets (solo en .env, nunca en config.yaml)
    anthropic_api_key: str | None = Field(default=None, repr=False)
    ollama_base_url: str | None = Field(default=None, repr=False)
    nvidia_api_key: str | None = Field(default=None, repr=False)


def load_config(config_path: str = "config.yaml") -> Settings:
    """Carga la configuración desde config.yaml y .env."""
    from pathlib import Path

    import yaml

    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    else:
        yaml_data = {}

    return Settings(**yaml_data)
