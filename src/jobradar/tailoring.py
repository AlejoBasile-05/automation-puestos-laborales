"""Generación y validación del CV adaptado (stub)."""


def generate_tailored_cv(job_requirements: dict, cv_master_path: str) -> dict:
    """Genera el CV adaptado (LLM) y lo valida (determinista)."""
    # TODO: implementar en Fase 4B
    raise NotImplementedError("Tailoring not implemented yet")


def validate_tailored_cv(tailored: dict, cv_master_path: str, supported_keywords: list[str]) -> tuple[bool, list[str]]:
    """Valida el CV adaptado contra las 7 reglas anti-invención.

    Returns:
        (is_valid, errors)
    """
    # TODO: implementar en Fase 4B
    raise NotImplementedError("Validator not implemented yet")
