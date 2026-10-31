"""Cliente factory para proveedores LLM."""

import os

from jobradar.llm.base import LLMClient
from jobradar.llm.nvidia_client import create_nvidia_client


def create_llm_client(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> LLMClient:
    """Crea el cliente LLM según el provider configurado.

    Args:
        provider: "anthropic" | "ollama" | "nvidia". Si None, lee de env LLM_PROVIDER.
        model: Nombre del modelo. Si None, usa default del provider.
        api_key: API key. Si None, lee de variable de entorno.
        base_url: URL base del endpoint (solo Ollama/Nvidia personalizado).

    Returns:
        Instancia de LLMClient configurada.
    """
    provider = provider or os.getenv("LLM_PROVIDER", "nvidia")

    if provider == "nvidia":
        return create_nvidia_client(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    elif provider == "ollama":
        from jobradar.llm.ollama_client import OllamaClient

        base_url_env: str | None = base_url or os.getenv("OLLAMA_BASE_URL")
        base_url_value: str = base_url_env or "http://localhost:11434"
        model_env: str | None = model or os.getenv("OLLAMA_MODEL")
        model_value: str = model_env or "mistral"
        return OllamaClient(base_url=base_url_value, model=model_value)
    elif provider == "anthropic":
        from jobradar.llm.anthropic_client import AnthropicClient

        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY requerida para provider anthropic")
        model_env_a: str | None = model or os.getenv("ANTHROPIC_MODEL")
        model_value_a: str = model_env_a or "claude-3-haiku-20240307"
        return AnthropicClient(api_key=api_key, model=model_value_a)
    else:
        raise ValueError(
            f"Provider LLM desconocido: {provider}. "
            f"Opciones válidas: anthropic, ollama, nvidia"
        )
