"""Extracción de requisitos ATS y matching determinista de keywords."""

import re
import unicodedata
from typing import Any, cast

import yaml


def normalize_text(text: str) -> str:
    """Normaliza texto para matching: minúsculas, sin acentos, sin puntuación."""
    text = text.lower().strip()
    # Quitar acentos
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Reemplazar puntuación y caracteres especiales con espacios
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Colapsar espacios múltiples
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_cv_master(cv_master_path: str) -> dict[str, Any]:
    """Carga el CV maestro desde YAML."""
    with open(cv_master_path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _collect_text_units(cv_master: dict) -> list[tuple[str, str]]:
    """Recopila unidades de texto del CV maestro con su id de evidencia.

    Cada unidad es (texto_normalizado, evidence_id).
    Indexamos: skills (nombre, aliases, tags), experiencia (bullets, título, empresa),
    educación, idiomas, certificaciones.
    También agrega versiones sin espacios para matching de siglas compuestas
    (ej: "Power BI" → también "powerbi").
    """
    units: list[tuple[str, str]] = []

    def _add(text: str, evidence_id: str) -> None:
        if text and text.strip():
            normalized = normalize_text(text)
            units.append((normalized, evidence_id))
            # También agregar versión sin espacios para siglas compuestas
            no_spaces = normalized.replace(" ", "")
            if no_spaces and no_spaces != normalized:
                units.append((no_spaces, evidence_id))

    # Skills: nombre, aliases, tags → nombre de la skill
    for skill in cv_master.get("skills", []):
        skill_name = skill.get("name", "")
        _add(skill_name, skill_name)
        for alias in skill.get("aliases", []):
            _add(alias, skill_name)
        for tag in skill.get("tags", []):
            _add(tag, skill_name)

    # Experiencia: título, empresa, texto de bullets → id del experience
    for exp in cv_master.get("experience", []):
        exp_id = exp.get("id", "")
        _add(exp.get("title", ""), exp_id)
        _add(exp.get("company", ""), exp_id)
        for bullet in exp.get("bullets", []):
            _add(bullet.get("text", ""), exp_id)

    # Educación: grado, institución → id de educación
    for edu in cv_master.get("education", []):
        edu_id = edu.get("id", "")
        _add(edu.get("degree", ""), edu_id)
        _add(edu.get("institution", ""), edu_id)

    # Idiomas: nombre → nombre del idioma
    for lang in cv_master.get("languages", []):
        _add(lang.get("name", ""), lang.get("name", ""))

    # Certificaciones
    for cert in cv_master.get("certifications", []):
        if isinstance(cert, str):
            _add(cert, cert)
        elif isinstance(cert, dict):
            _add(cert.get("name", ""), cert.get("name", ""))

    return units


def _term_variants(term_normalized: str) -> list[str]:
    """Genera variantes de un término para matching.

    Incluye: el término tal cual, con 's' al final, sin 's' final.
    """
    variants = {term_normalized}
    variants.add(term_normalized + "s")
    if term_normalized.endswith("s") and len(term_normalized) > 1:
        variants.add(term_normalized[:-1])
    return list(variants)


def _find_evidence(term_normalized: str, units: list[tuple[str, str]]) -> list[str]:
    """Busca un término con límites de palabra en las unidades de texto.

    Para términos sin espacios (ej: "powerbi"), también busca como substring
    en texto sin espacios, pero solo si no es subcadena de una palabra más larga
    en el texto con espacios (evita falsos positivos como "java" en "javascript").
    """
    evidence_ids: list[str] = []
    has_space = " " in term_normalized

    # Texto concatenado con espacios (solo versiones con espacios, para evitar falsos positivos
    # por las versiones sin espacios que agregamos para siglas compuestas)
    text_with_spaces_clean = " ".join(
        u[0] for u in units if " " in u[0]
    )
    text_no_spaces = text_with_spaces_clean.replace(" ", "")

    # Verificar si el término es subcadena de una palabra más larga (para evitar falsos positivos)
    def _is_substring_of_longer_word(term: str) -> bool:
        for w in text_with_spaces_clean.split():
            if term in w and len(w) > len(term):
                return True
        return False

    is_substring_of_longer = _is_substring_of_longer_word(term_normalized)

    for text_normalized, evidence_id in units:
        found = False

        if has_space:
            # Término de varias palabras: buscar con límites de palabra
            pattern = r"\b" + re.escape(term_normalized) + r"\b"
            found = bool(re.search(pattern, text_normalized))
        else:
            # Término de una palabra: buscar con límites de palabra
            pattern = r"\b" + re.escape(term_normalized) + r"\b"
            if re.search(pattern, text_normalized):
                found = True
            # También buscar como substring en texto sin espacios,
            # pero solo si no es subcadena de una palabra más larga
            elif not is_substring_of_longer and term_normalized in text_no_spaces:
                # Verificar si esta unidad específica contiene el término sin espacios
                if term_normalized in text_normalized.replace(" ", ""):
                    found = True

        if found and evidence_id not in evidence_ids:
            evidence_ids.append(evidence_id)

    return evidence_ids


def match_keywords(keywords: list[dict], cv_master_path: str) -> list[dict]:
    """Matching determinista de keywords contra CV maestro (sin LLM).

    Args:
        keywords: Lista de dicts con 'term', 'type', 'importance', 'synonyms' (opcional).
        cv_master_path: Ruta al archivo YAML del CV maestro.

    Returns:
        Lista de dicts con 'term', 'type', 'importance', 'status' ('supported' | 'gap'), 'evidence_ids'.
    """
    units = _collect_text_units(_load_cv_master(cv_master_path))

    results: list[dict] = []

    for kw in keywords:
        term = kw["term"]
        term_normalized = normalize_text(term)
        synonyms = kw.get("synonyms", [])

        # Recopilar todos los términos a buscar: principal + synonyms
        search_terms = [term_normalized] + [normalize_text(s) for s in synonyms if s]

        evidence_ids: list[str] = []
        for search_term in search_terms:
            for variant in _term_variants(search_term):
                found = _find_evidence(variant, units)
                for eid in found:
                    if eid not in evidence_ids:
                        evidence_ids.append(eid)

        status = "supported" if evidence_ids else "gap"

        results.append({
            "term": term,
            "type": kw.get("type", ""),
            "importance": kw.get("importance", ""),
            "status": status,
            "evidence_ids": evidence_ids,
        })

    return results


def extract_requirements(job_description: str) -> dict:
    """Extrae keywords y knockouts de la descripción de la vacante.

    Esta función es un placeholder. La extracción real se hace con el LLM
    usando prompts/ats_extract_v1.md desde scoring.py.

    Nota: el LLM solo se usa para EXTRAER requisitos, nunca para decidir
    si algo está respaldado en el CV.
    """
    return {
        "job_title_exact": "",
        "language": "es",
        "keywords": [],
        "knockouts": [],
    }
