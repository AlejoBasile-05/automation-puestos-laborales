"""Cliente Ollama (stub - opcional)."""

from pydantic import BaseModel

from jobradar.llm.base import LLMClient


class OllamaClient(LLMClient):
    """Cliente para Ollama local."""

    def __init__(self, base_url: str, model: str):
        self._base_url = base_url
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        # TODO: implementar en Fase 3 (opcional)
        raise NotImplementedError("Ollama client not implemented yet")
