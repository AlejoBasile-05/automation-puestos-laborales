"""Filtros eliminatorios (knockouts) - comparación con eligibility del CV maestro."""

from typing import Any, cast

import yaml


def _load_cv_master(cv_master_path: str) -> dict[str, Any]:
    """Carga el CV maestro desde YAML."""
    with open(cv_master_path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))

def _check_years_experience(knockout: dict, cv_master: dict) -> str:
    """Evalúa knockout de años de experiencia de forma determinista."""
    eligibility = cv_master.get("eligibility", {})
    years_exp = eligibility.get("years_experience", {})
    total_years = years_exp.get("total", 0)
    by_area = years_exp.get("by_area", {})

    required_value = knockout.get("value", 0)
    area = knockout.get("area")

    if area:
        area_years = by_area.get(area, 0)
        if area_years >= required_value:
            return "met"
        return "not_met"
    else:
        if total_years >= required_value:
            return "met"
        return "not_met"


def _check_language(knockout: dict, cv_master: dict) -> str:
    """Evalúa knockout de idioma de forma determinista."""
    required_level = knockout.get("value", "")
    languages = cv_master.get("languages", [])

    # Orden de niveles conocido
    level_order = {"basico": 1, "a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6, "nativo": 7}

    for lang in languages:
        lang_name = lang.get("name", "").lower()
        lang_level = lang.get("level", "").lower()

        # Buscar el idioma en el knockout (ej: "Inglés B2" contiene "Inglés")
        req_term = knockout.get("requirement", "").lower()
        if lang_name in req_term or req_term in lang_name:
            user_level = level_order.get(lang_level, 0)
            req_level = level_order.get(required_level.lower(), 0)
            if user_level >= req_level:
                return "met"
            return "not_met"

    return "not_met"


def _check_education(knockout: dict, cv_master: dict) -> str:
    """Evalúa knockout de educación de forma determinista."""
    education = cv_master.get("education", [])
    requirement = knockout.get("requirement", "").lower()

    for edu in education:
        degree = edu.get("degree", "").lower()
        institution = edu.get("institution", "").lower()
        if degree in requirement or requirement in degree or institution in requirement:
            return "met"

    return "not_met"


def _check_location(knockout: dict, cv_master: dict) -> str:
    """Evalúa knockout de ubicación de forma determinista."""
    basics = cv_master.get("basics", {})
    location = basics.get("location", "").lower()
    requirement = knockout.get("requirement", "").lower()

    remote_ok = cv_master.get("eligibility", {}).get("remote_ok", False)
    relocation = cv_master.get("eligibility", {}).get("relocation", False)

    if "remote" in requirement and remote_ok:
        return "met"
    if location in requirement or requirement in location:
        return "met"
    if relocation and ("relocation" in requirement or "traslado" in requirement):
        return "met"

    return "not_met"


def _check_work_authorization(knockout: dict, cv_master: dict) -> str:
    """Evalúa knockout de autorización de trabajo de forma determinista."""
    work_auth = cv_master.get("eligibility", {}).get("work_authorization", [])
    requirement = knockout.get("requirement", "").lower()

    for auth in work_auth:
        if auth.lower() in requirement or requirement in auth.lower():
            return "met"

    return "not_met"


def check_knockouts(knockouts: list[dict], cv_master_path: str) -> list[dict]:
    """Compara knockouts contra el CV maestro y devuelve met|not_met|unknown.

    Años, idiomas y estudios se evalúan de forma determinista.
    Ante la duda, se devuelve unknown (nunca se asume que se cumple).

    Args:
        knockouts: Lista de dicts con 'type', 'requirement', 'value', 'area', 'mandatory'.
        cv_master_path: Ruta al archivo YAML del CV maestro.

    Returns:
        Lista de dicts con 'type', 'requirement', 'status' (met|not_met|unknown), 'evidence'.
    """
    cv_master = _load_cv_master(cv_master_path)

    results: list[dict] = []

    for ko in knockouts:
        ko_type = ko.get("type", "other")

        if ko_type == "years_experience":
            status = _check_years_experience(ko, cv_master)
        elif ko_type == "language":
            status = _check_language(ko, cv_master)
        elif ko_type == "education":
            status = _check_education(ko, cv_master)
        elif ko_type == "location":
            status = _check_location(ko, cv_master)
        elif ko_type == "work_authorization":
            status = _check_work_authorization(ko, cv_master)
        else:
            # Tipos no determinísticos: unknown (nunca asumir)
            status = "unknown"

        results.append({
            "type": ko_type,
            "requirement": ko.get("requirement", ""),
            "value": ko.get("value"),
            "area": ko.get("area"),
            "mandatory": ko.get("mandatory", False),
            "status": status,
            "evidence": f"Evaluado contra CV maestro: {cv_master_path}",
        })

    return results
