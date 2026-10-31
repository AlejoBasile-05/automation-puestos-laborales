"""Cliente Nvidia NIM (API gratuita con API key)."""

import json
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel

from jobradar.llm.base import LLMClient


class NvidiaClient(LLMClient):
    """Cliente para Nvidia NIM (modelos gratuitos con API key).

    Usa el endpoint compatible con OpenAI de Nvidia NIM.
    Modelo recomendado gratuito: nvidia/nemotron-mini-4b-instruct
    """

    BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nemotron-mini-4b-instruct",
        base_url: str | None = None,
        timeout_seconds: int = 30,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url or self.BASE_URL
        self._timeout = timeout_seconds

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
        """Envía una solicitud de completación JSON a Nvidia NIM."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        self._base_url,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                content = data["choices"][0]["message"]["content"]
                return schema.model_validate_json(content)

            except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)  # backoff exponencial
                    continue
                raise

        raise RuntimeError(f"Nvidia API falló tras 3 intentos: {last_error}")


def create_nvidia_client(
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> NvidiaClient:
    """Crea un cliente Nvidia con credenciales del entorno o parámetros."""
    api_key = api_key or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise ValueError(
            "NVIDIA_API_KEY no configurada. "
            "Obtén una key gratuita en https://build.nvidia.com/"
        )

    model_value: str = model or os.getenv("NVIDIA_MODEL") or "nvidia/nemotron-mini-4b-instruct"
    assert model_value is not None
    base_url_value: str | None = base_url or os.getenv("NVIDIA_BASE_URL")

    return NvidiaClient(api_key=api_key, model=model_value, base_url=base_url_value)
