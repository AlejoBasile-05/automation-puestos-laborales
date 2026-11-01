"""Extracción de requisitos ATS y matching determinista de keywords."""

import hashlib
import re
import unicodedata
from collections.abc import Callable
from typing import Any, cast

import yaml
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobradar.db.models import Job, JobRequirement
from jobradar.llm.base import LLMClient
from jobradar.paths import prompt_path


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


PROMPT_VERSION = "ats_extract_v1"
PROMPT_PATH = prompt_path("ats_extract_v1.md")

EXTRACTION_SYSTEM_PROMPT = (
    "Eres un analista de reclutamiento. Extraes los requisitos de una vacante "
    "para análisis ATS. Responde siempre en JSON válido y no inventes requisitos."
)

_KEYWORD_TYPES = frozenset(
    {
        "tool",
        "hard_skill",
        "certification",
        "title",
        "domain",
        "methodology",
        "soft_skill",
    }
)
_KEYWORD_IMPORTANCES = frozenset({"required", "preferred", "mentioned"})
_KNOCKOUT_TYPES = frozenset(
    {
        "years_experience",
        "education",
        "language",
        "location",
        "certification",
        "work_authorization",
        "other",
    }
)


class ExtractedKeyword(BaseModel):
    """Keyword extraída de la vacante."""

    term: str = Field(min_length=1)
    type: str = "hard_skill"
    importance: str = "mentioned"
    synonyms: list[str] = Field(default_factory=list)
    frequency_in_posting: int = Field(default=0, ge=0)

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in _KEYWORD_TYPES else "hard_skill"

    @field_validator("importance")
    @classmethod
    def _normalize_importance(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in _KEYWORD_IMPORTANCES else "mentioned"


class ExtractedKnockout(BaseModel):
    """Filtro eliminatorio extraído de la vacante."""

    type: str = "other"
    requirement: str = ""
    value: float | None = None
    area: str | None = None
    mandatory: bool = False

    @field_validator("type")
    @classmethod
    def _normalize_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        return normalized if normalized in _KNOCKOUT_TYPES else "other"


class ATSExtraction(BaseModel):
    """Salida validada de la extracción de requisitos (AGENTS.md §9.1)."""

    job_title_exact: str = ""
    language: str = "es"
    keywords: list[ExtractedKeyword] = Field(default_factory=list)
    knockouts: list[ExtractedKnockout] = Field(default_factory=list)

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.startswith("en"):
            return "en"
        if normalized.startswith("es"):
            return "es"
        return "es"


def extract_requirements(
    job_description: str,
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Extrae keywords y knockouts de la descripción de la vacante.

    La extracción la hace el LLM con ``src/jobradar/prompts/ats_extract_v1.md``. El LLM solo
    EXTRAE requisitos: nunca decide si algo está respaldado en el CV. Esa
    decisión es determinista y vive en :func:`match_keywords`.

    Args:
        job_description: Texto de la vacante.
        llm: Cliente LLM. Si es ``None`` se crea uno con la configuración.

    Returns:
        Diccionario validado con ``job_title_exact``, ``language``,
        ``keywords`` y ``knockouts``.

    Raises:
        RuntimeError: si la extracción falla tras el reintento.
    """
    client = llm or _default_llm()
    prompt = render_extraction_prompt(job_description)
    return _extract_with_retry(client, prompt).model_dump()


def render_extraction_prompt(
    job_description: str,
    template: str | None = None,
) -> str:
    """Inserta la descripción de la vacante en la plantilla del prompt."""
    base = template if template is not None else load_extraction_prompt()
    return base.replace("{job_description}", job_description)


def load_extraction_prompt() -> str:
    """Carga la plantilla del prompt de extracción."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"No se encontró {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def compute_description_hash(job_description: str) -> str:
    """Hash SHA256 de la descripción, clave de caché de requisitos."""
    return hashlib.sha256(job_description.encode("utf-8")).hexdigest()


def ensure_requirements(
    job: Job,
    session_factory: Callable[[], Session],
    llm: LLMClient,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any]:
    """Devuelve los requisitos de una vacante, usando la caché de ``job_requirements``.

    La caché se indexa por ``(job_id, description_hash, prompt_version)``: si no
    cambió la descripción ni el prompt, no se vuelve a gastar una llamada al LLM.
    """
    description = job.description_text or ""
    description_hash = compute_description_hash(description)

    with session_factory() as session:
        cached = session.scalars(
            select(JobRequirement).where(
                JobRequirement.job_id == job.id,
                JobRequirement.description_hash == description_hash,
                JobRequirement.prompt_version == prompt_version,
            )
        ).first()
        if cached is not None:
            return _cached_payload(cached)

    extraction = extract_requirements(description, llm=llm)

    with session_factory() as session:
        session.add(
            JobRequirement(
                job_id=job.id,
                description_hash=description_hash,
                prompt_version=prompt_version,
                model=llm.model_name,
                keywords_json={
                    "job_title_exact": extraction["job_title_exact"],
                    "language": extraction["language"],
                    "keywords": extraction["keywords"],
                },
                knockouts_json=extraction["knockouts"],
            )
        )
        session.commit()

    return extraction


def _cached_payload(record: JobRequirement) -> dict[str, Any]:
    """Reconstruye el diccionario de requisitos desde una fila cacheada."""
    stored = cast(Any, record.keywords_json) or {}
    if isinstance(stored, dict):
        keywords = stored.get("keywords", [])
        job_title = stored.get("job_title_exact", "")
        language = stored.get("language", "es")
    else:
        # Formato plano (solo lista de keywords) por compatibilidad.
        keywords = stored
        job_title = ""
        language = "es"

    return {
        "job_title_exact": job_title,
        "language": language,
        "keywords": keywords,
        "knockouts": cast(Any, record.knockouts_json) or [],
    }


def _extract_with_retry(
    llm: LLMClient,
    prompt: str,
    attempts: int = 2,
) -> ATSExtraction:
    """Llama al LLM y valida la salida, con un único reintento."""
    last_error: Exception | None = None

    for _ in range(attempts):
        try:
            result = llm.complete_json(
                system=EXTRACTION_SYSTEM_PROMPT,
                user=prompt,
                schema=ATSExtraction,
                temperature=0.0,
            )
        except (ValueError, RuntimeError) as exc:
            last_error = exc
            continue

        if isinstance(result, ATSExtraction):
            return result
        last_error = TypeError(f"Se esperaba ATSExtraction, se obtuvo {type(result)}")

    raise RuntimeError(
        f"La extracción de requisitos falló tras {attempts} intentos: {last_error}"
    )


def _default_llm() -> LLMClient:
    """Crea el cliente LLM a partir de ``config.yaml``."""
    from jobradar.config import load_config
    from jobradar.llm.factory import create_llm_client

    config = load_config()
    return create_llm_client(
        provider=config.llm.provider,
        model=config.llm.model_scoring,
    )

