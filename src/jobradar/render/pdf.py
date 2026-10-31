"""Generador de PDF para CV ATS con WeasyPrint."""

import os
import re
import unicodedata
from typing import Any, cast

import yaml
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration


def _slugify_name(name: str) -> str:
    """Crea un nombre de archivo limpio sin espacios, acentos ni caracteres especiales."""
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = re.sub(r"[^a-zA-Z0-9]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def _load_cv_master(cv_master_path: str = "data/cv_master.yaml") -> dict[str, Any]:
    """Carga el CV maestro desde YAML."""
    with open(cv_master_path, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _build_render_context(
    tailored_cv_json: dict, cv_master: dict
) -> dict[str, Any]:
    """Combina el tailored_cv_json con los datos del CV maestro para renderizar.

    El tailored_cv_json tiene:
        headline, summary, experience (con experience_id, bullet_ids, rewrites),
        skills, education_ids, keywords_used, cover_message

    El CV maestro tiene:
        basics (name, email, phone, location, links),
        education (id, institution, degree, year),
        experience (id, company, title, start, end, location, bullets con id y text),
        skills, certifications, languages
    """
    # Indexar educación del maestro por id
    edu_map = {e["id"]: e for e in cv_master.get("education", [])}
    # Indexar experiencia del maestro por id
    exp_map = {e["id"]: e for e in cv_master.get("experience", [])}

    # Construir lista de experiencia para renderizar
    render_experience = []
    for exp in tailored_cv_json.get("experience", []):
        exp_id = exp["experience_id"]
        master_exp = exp_map.get(exp_id, {})
        bullets_map = {}
        for b in master_exp.get("bullets", []):
            bullets_map[b["id"]] = b
        render_experience.append({
            "title": master_exp.get("title", ""),
            "company": master_exp.get("company", ""),
            "start": master_exp.get("start", ""),
            "end": master_exp.get("end", ""),
            "location": master_exp.get("location", ""),
            "bullet_ids": exp["bullet_ids"],
            "rewrites": exp.get("rewrites", {}),
            "bullets_map": bullets_map,
        })

    # Construir lista de educación para renderizar
    render_education = []
    for edu_id in tailored_cv_json.get("education_ids", []):
        edu = edu_map.get(edu_id, {})
        render_education.append({
            "degree": edu.get("degree", ""),
            "institution": edu.get("institution", ""),
            "year": edu.get("year", ""),
        })

    # Certificaciones del maestro
    certifications = []
    for cert in cv_master.get("certifications", []):
        if isinstance(cert, str):
            certifications.append(cert)
        elif isinstance(cert, dict):
            certifications.append(cert.get("name", ""))

    return {
        "basics": cv_master.get("basics", {}),
        "headline": tailored_cv_json.get("headline", ""),
        "summary": tailored_cv_json.get("summary", ""),
        "skills": tailored_cv_json.get("skills", []),
        "experience": render_experience,
        "education": render_education,
        "certifications": certifications,
        "languages": cv_master.get("languages", []),
    }


def generate_pdf(
    tailored_cv_json: dict,
    output_dir: str,
    cv_master_path: str = "data/cv_master.yaml",
) -> str:
    """Genera un PDF ATS a partir del CV adaptado.

    Args:
        tailored_cv_json: Diccionario con el CV adaptado (salida de tailoring).
        output_dir: Directorio de salida para el PDF.
        cv_master_path: Ruta al CV maestro (para datos básicos).

    Returns:
        Ruta al archivo PDF generado.
    """
    cv_master = _load_cv_master(cv_master_path)
    context = _build_render_context(tailored_cv_json, cv_master)

    # Renderizar plantilla Jinja2
    from jinja2 import Environment, FileSystemLoader

    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    template = env.get_template("cv_ats.html.j2")
    html = template.render(**context)

    # Crear directorio de salida
    os.makedirs(output_dir, exist_ok=True)

    # Nombre de archivo limpio
    name = context["basics"].get("name", "CV")
    filename = f"{_slugify_name(name)}_CV.pdf"
    output_path = os.path.join(output_dir, filename)

    # Generar PDF con WeasyPrint
    html_obj = HTML(string=html, base_url=".")
    font_config = FontConfiguration()
    html_obj.write_pdf(output_path, font_config=font_config)

    return output_path
