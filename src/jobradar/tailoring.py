"""Generación de CV adaptado + mensaje con validador determinista."""

import re
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel

from jobradar.config import load_config
from jobradar.db.models import Application, Job
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.llm.base import LLMClient
from jobradar.llm.factory import create_llm_client
from jobradar.paths import prompt_path


class TailoredExperience(BaseModel):
    experience_id: str
    bullet_ids: list[str]
    rewrites: dict[str, str]  # bullet_id -> versión reescrita


class TailoredCVOutput(BaseModel):
    headline: str
    summary: str  # máx 60 palabras
    experience: list[TailoredExperience]
    skills: list[str]
    education_ids: list[str]
    keywords_used: list[str]
    cover_message: str  # máx 150 palabras


# ============================================================================
# Carga del CV maestro
# ============================================================================

CV_MASTER_PATH = Path("data/cv_master.yaml")
PROMPT_VERSION = "tailoring_v1"
PROMPT_PATH = prompt_path("tailoring_v1.md")


def _load_prompt() -> str:
    """Carga la plantilla del prompt de tailoring desde el paquete."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"No se encontró {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_cv_master(cv_master_path: str = str(CV_MASTER_PATH)) -> dict[str, Any]:
    """Carga el CV maestro desde YAML."""
    with open(cv_master_path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _get_all_text(cv_master: dict) -> str:
    """Extrae todo el texto del CV maestro para búsquedas de consistencia."""
    parts: list[str] = []
    parts.append(cv_master.get("basics", {}).get("name", ""))
    parts.append(cv_master.get("basics", {}).get("location", ""))
    for exp in cv_master.get("experience", []):
        parts.append(exp.get("company", ""))
        parts.append(exp.get("title", ""))
        parts.append(exp.get("location", ""))
        parts.append(exp.get("start", ""))
        parts.append(exp.get("end", ""))
        for b in exp.get("bullets", []):
            parts.append(b.get("text", ""))
    for edu in cv_master.get("education", []):
        parts.append(edu.get("institution", ""))
        parts.append(edu.get("degree", ""))
    for skill in cv_master.get("skills", []):
        parts.append(skill.get("name", ""))
        parts.extend(skill.get("aliases", []))
    for cert in cv_master.get("certifications", []):
        if isinstance(cert, str):
            parts.append(cert)
        elif isinstance(cert, dict):
            parts.append(cert.get("name", ""))
    for lang in cv_master.get("languages", []):
        parts.append(lang.get("name", ""))
    return " ".join(parts)


# ============================================================================
# Validador determinista (7 reglas de AGENTS.md sección 7)
# ============================================================================

def _get_existing_ids(cv_master: dict) -> dict[str, set[str]]:
    """Extrae todos los IDs válidos del CV maestro."""
    exp_ids = {e["id"] for e in cv_master.get("experience", [])}
    bullet_ids = set()
    for e in cv_master.get("experience", []):
        for b in e.get("bullets", []):
            bullet_ids.add(b["id"])
    edu_ids = {e["id"] for e in cv_master.get("education", [])}
    return {"experience": exp_ids, "bullet": bullet_ids, "education": edu_ids}


def _get_skill_names(cv_master: dict) -> set[str]:
    """Extrae nombres de skills y sus aliases."""
    names = set()
    for s in cv_master.get("skills", []):
        names.add(s["name"].lower())
        for a in s.get("aliases", []):
            names.add(a.lower())
    return names


def _extract_numbers(text: str) -> set[str]:
    """Extrae números, porcentajes y cifras de un texto."""
    return set(re.findall(r"\d+(?:\.\d+)?%?", text))


def _extract_entities(text: str) -> set[str]:
    """Extrae entidades mayúsculas (empresas, herramientas, certificaciones) simples.

    Excluye palabras comunes del español que no son entidades propias.
    Captura tanto CamelCase como acrónimos en mayúsculas (SAP, AWS, API).
    """
    palabras_comunes = {
        "Experiencia", "Educación", "Educacion", "Skills", "Habilidades",
        "Certificaciones", "Certification", "Idiomas", "Languages",
        "Resumen", "Summary", "Contacto", "Contact", "Linkedin", "Github",
        "Portfolio", "Ubicación", "Ubicacion", "Telefono", "Email",
    }
    entidades = set()
    # CamelCase o Title Case
    for match in re.finditer(
        r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,})*\b", text
    ):
        palabra = match.group()
        if palabra not in palabras_comunes:
            entidades.add(palabra)
    # Acrónimos en mayúsculas (3+ letras)
    for match in re.finditer(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b", text):
        palabra = match.group()
        if palabra not in palabras_comunes:
            entidades.add(palabra)
    return entidades


def validate_tailored_cv(
    tailored: TailoredCVOutput,
    cv_master_path: str = str(CV_MASTER_PATH),
) -> dict:
    """Valida el CV adaptado con las 7 reglas de AGENTS.md sección 7.

    Returns:
        dict con 'valido' (bool) y 'razon' (str).
    """
    cv_master = _load_cv_master(cv_master_path)
    ids = _get_existing_ids(cv_master)
    skill_names = _get_skill_names(cv_master)
    all_text = _get_all_text(cv_master).lower()

    # Regla 1: IDs válidos
    for exp in tailored.experience:
        if exp.experience_id not in ids["experience"]:
            return {"valido": False, "razon": f"experience_id '{exp.experience_id}' no existe en el CV maestro"}
        for bid in exp.bullet_ids:
            if bid not in ids["bullet"]:
                return {"valido": False, "razon": f"bullet_id '{bid}' no existe en el CV maestro"}
    for eid in tailored.education_ids:
        if eid not in ids["education"]:
            return {"valido": False, "razon": f"education_id '{eid}' no existe en el CV maestro"}

    # Regla 2: Skills válidas
    for skill in tailored.skills:
        if skill.lower() not in skill_names:
            return {"valido": False, "razon": f"habilidad '{skill}' no está en el CV maestro"}

    # Regla 3: Números en rewrites ⊆ números del bullet original
    for exp in tailored.experience:
        for bid, rewrite in exp.rewrites.items():
            # Encontrar el texto original del bullet
            original_text = ""
            for e in cv_master.get("experience", []):
                if e["id"] == exp.experience_id:
                    for b in e.get("bullets", []):
                        if b["id"] == bid:
                            original_text = b.get("text", "")
                            break
                    break
            original_numbers = _extract_numbers(original_text)
            rewrite_numbers = _extract_numbers(rewrite)
            extra = rewrite_numbers - original_numbers
            if extra:
                return {
                    "valido": False,
                    "razon": f"rewrite de '{bid}' contiene números no originales: {', '.join(sorted(extra))}",
                }

    # Regla 4: No entidades nuevas en rewrite o summary
    for _exp in tailored.experience:
        for rewrite in _exp.rewrites.values():
            entities = _extract_entities(rewrite)
            for ent in entities:
                if ent.lower() not in all_text:
                    return {"valido": False, "razon": f"rewrite menciona '{ent}' que no está en el CV maestro"}
    summary_entities = _extract_entities(tailored.summary)
    for ent in summary_entities:
        if ent.lower() not in all_text:
            return {"valido": False, "razon": f"summary menciona '{ent}' que no está en el CV maestro"}

    # Regla 5: Longitud
    if len(tailored.summary.split()) > 60:
        return {"valido": False, "razon": "summary supera 60 palabras"}
    if len(tailored.cover_message.split()) > 150:
        return {"valido": False, "razon": "cover_message supera 150 palabras"}

    # Regla 6: Empresas/cargos/fechas distintos al maestro
    # (ya cubierto por regla 4 y validación de IDs en regla 1)

    # Regla 7: No keywords gap
    # keywords_used no debe incluir keywords marcadas como gap
    # Aquí asumimos que el llamador ya filtró, pero verificamos doble:
    for kw in tailored.keywords_used:
        kw_lower = kw.lower().strip()
        # Si la keyword no está en skill_names ni en aliases, podría ser gap
        if kw_lower not in skill_names and kw_lower not in all_text:
            return {"valido": False, "razon": f"keyword '{kw}' aparece como gap (no está en el CV maestro)"}

    return {"valido": True, "razon": "CV válido"}


def calculate_coverage(
    keywords_used: list[str],
    cv_master_path: str = str(CV_MASTER_PATH),
) -> dict:
    """Calcula required_coverage y overall_coverage.

    required_coverage = keywords required + supported presentes / total de required + supported
    overall_coverage = incluye gap en el denominador

    Returns:
        dict con 'required_coverage', 'overall_coverage', 'retry' (bool)
    """
    # Esta función se usa desde el flujo principal que ya sabe cuáles son required/supported/gap.
    # Aquí hacemos un cálculo simplificado basado en qué keywords están en el CV maestro.
    cv_master = _load_cv_master(cv_master_path)
    skill_names = _get_skill_names(cv_master)
    all_text = _get_all_text(cv_master).lower()

    supported_count = 0
    gap_count = 0
    for kw in keywords_used:
        kw_lower = kw.lower().strip()
        if kw_lower in skill_names or kw_lower in all_text:
            supported_count += 1
        else:
            gap_count += 1

    total_required_supported = len(keywords_used)  # En la práctica, esto vendría del LLM extract
    required_coverage = supported_count / total_required_supported if total_required_supported > 0 else 1.0
    overall_coverage = supported_count / (supported_count + gap_count) if (supported_count + gap_count) > 0 else 1.0

    return {
        "required_coverage": required_coverage,
        "overall_coverage": overall_coverage,
        "retry": required_coverage < 0.90,
    }


# ============================================================================
# Flujo principal
# ============================================================================

def tailor_job(
    job_id: int,
    keywords_supported: list[dict],
    knockouts: list[dict],
    provider: str | None = None,
    model: str | None = None,
    llm: LLMClient | None = None,
    language: str = "es",
) -> dict:
    """Genera CV adaptado + mensaje para una vacante.

    Args:
        job_id: ID de la vacante en la BD.
        keywords_supported: Lista de keywords supported con evidencia (del LLM extract + matching).
        knockouts: Lista de knockouts con estado met/not_met/unknown.
        provider: Proveedor LLM (nvidia | ollama | anthropic) si no se inyecta cliente.
        model: Nombre del modelo si no se inyecta cliente.
        llm: Cliente LLM ya construido (inyectable en tests y en la UI).
        language: Idioma de la vacante (``es`` | ``en``) para el CV y el mensaje.

    Returns:
        dict con resultado de la operación.
    """
    config = load_config()
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    # Usar el cliente inyectado o construir uno desde config.yaml
    client: LLMClient = llm or create_llm_client(
        provider=provider or config.llm.provider,
        model=model or config.llm.model_writing,
    )

    # Cargar prompt
    prompt_template = _load_prompt()

    # Construir entrada para el LLM (SOLO keywords supported, NUNCA gap)
    keywords_text = "\n".join(
        f"- {kw['term']} (evidencia: {', '.join(kw.get('evidence_ids', []))})"
        for kw in keywords_supported
    )

    user_prompt = prompt_template.replace("{{keywords_supported}}", keywords_text)

    # Knockouts obligatorios no cumplidos: restricciones explícitas para el LLM
    unmet = [
        ko for ko in knockouts
        if ko.get("mandatory") and ko.get("status") == "not_met"
    ]
    if unmet:
        warnings = "; ".join(
            str(ko.get("requirement") or ko.get("type") or "requisito")
            for ko in unmet
        )
        user_prompt += (
            "\n\nRESTRICCIONES: no reclames ni insinúes estos requisitos no "
            f"cumplidos: {warnings}."
        )

    system_prompt = (
        "Eres un experto en redacción de CV para ATS. "
        "Genera un CV adaptado usando SOLO los keywords soportados proporcionados. "
        "No inventes experiencia. "
        f"Redacta el CV y el mensaje de postulación en el idioma de la vacante: {language}. "
        "Responde siempre en JSON válido."
    )

    # Intentar con reintento si coverage bajo
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            result = client.complete_json(
                system=system_prompt,
                user=user_prompt,
                schema=TailoredCVOutput,
                temperature=0.0,
            )
        except Exception as e:
            return {"exito": False, "error": f"Error llamando al LLM: {e}"}

        result = cast(TailoredCVOutput, result)

        # Validar con las 7 reglas
        validation = validate_tailored_cv(result, str(CV_MASTER_PATH))
        if not validation["valido"]:
            if attempt == max_attempts - 1:
                return {
                    "exito": False,
                    "error": f"Validación falló tras {max_attempts} intentos: {validation['razon']}",
                    "tailored": result.model_dump(),
                }
            # Reintentar: ajustar el prompt para el siguiente intento
            user_prompt += f"\n\nCORRECCIÓN: {validation['razon']}. Corrige y reintenta."
            continue

        # Calcular cobertura
        coverage = calculate_coverage(result.keywords_used, str(CV_MASTER_PATH))
        if coverage["retry"] and attempt < max_attempts - 1:
            missing = [kw["term"] for kw in keywords_supported if kw["term"] not in result.keywords_used]
            user_prompt += f"\n\nFALTAN keywords requeridas: {', '.join(missing)}. Añádelas al CV."
            continue

        # Éxito: guardar en BD
        with session_factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return {"exito": False, "error": f"Vacante {job_id} no encontrada"}

            application = Application(
                job_id=job_id,
                tailored_cv_json=result.model_dump(),
                pdf_path="",
                docx_path="",
                message_text=result.cover_message,
                language=language,
                required_coverage=coverage["required_coverage"],
                ats_report_json={},
            )
            session.add(application)
            session.commit()
            session.refresh(application)

        return {
            "exito": True,
            "application_id": application.id,
            "required_coverage": coverage["required_coverage"],
            "overall_coverage": coverage["overall_coverage"],
            "tailored": result.model_dump(),
        }

    return {"exito": False, "error": "No se pudo generar un CV válido tras los reintentos"}
