"""Cliente Anthropic (stub)."""

from pydantic import BaseModel

from jobradar.llm.base import LLMClient


class AnthropicClient(LLMClient):
    """Cliente para API de Anthropic."""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
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
        # TODO: implementar en Fase 3
        raise NotImplementedError("Anthropic client not implemented yet")
