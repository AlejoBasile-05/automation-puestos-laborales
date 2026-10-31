"""Protocolo base para clientes LLM."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMClient(ABC):
    """Interfaz común para proveedores LLM."""

    @abstractmethod
    def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        """Completación que devuelve JSON validado contra el schema."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Nombre del modelo en uso."""
        ...
