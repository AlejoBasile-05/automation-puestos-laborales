"""Generador de DOCX para CV ATS con python-docx."""

import os
import re
import unicodedata
from typing import Any, cast

import yaml
from docx import Document
from docx.shared import Pt


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
    """Combina el tailored_cv_json con los datos del CV maestro para renderizar."""
    edu_map = {e["id"]: e for e in cv_master.get("education", [])}
    exp_map = {e["id"]: e for e in cv_master.get("experience", [])}

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

    render_education = []
    for edu_id in tailored_cv_json.get("education_ids", []):
        edu = edu_map.get(edu_id, {})
        render_education.append({
            "degree": edu.get("degree", ""),
            "institution": edu.get("institution", ""),
            "year": edu.get("year", ""),
        })

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


def generate_docx(
    tailored_cv_json: dict,
    output_dir: str,
    cv_master_path: str = "data/cv_master.yaml",
) -> str:
    """Genera un DOCX ATS a partir del CV adaptado.

    Args:
        tailored_cv_json: Diccionario con el CV adaptado.
        output_dir: Directorio de salida para el DOCX.
        cv_master_path: Ruta al CV maestro (para datos básicos).

    Returns:
        Ruta al archivo DOCX generado.
    """
    cv_master = _load_cv_master(cv_master_path)
    context = _build_render_context(tailored_cv_json, cv_master)

    os.makedirs(output_dir, exist_ok=True)

    name = context["basics"].get("name", "CV")
    filename = f"{_slugify_name(name)}_CV.docx"
    output_path = os.path.join(output_dir, filename)

    doc = Document()

    # Fuente por defecto
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(11)

    # Nombre
    doc.add_heading(context["basics"].get("name", ""), level=0)

    # Contacto
    doc.add_heading("Contacto", level=1)
    doc.add_paragraph(f"Email: {context['basics'].get('email', '')}")
    doc.add_paragraph(f"Teléfono: {context['basics'].get('phone', '')}")
    doc.add_paragraph(f"Ubicación: {context['basics'].get('location', '')}")
    for link in context["basics"].get("links", []):
        doc.add_paragraph(f"{link.get('label', '')}: {link.get('url', '')}")

    # Resumen
    doc.add_heading("Resumen", level=1)
    doc.add_paragraph(context["headline"])
    doc.add_paragraph(context["summary"])

    # Habilidades
    doc.add_heading("Habilidades", level=1)
    doc.add_paragraph(", ".join(context["skills"]))

    # Experiencia
    doc.add_heading("Experiencia profesional", level=1)
    for job in context["experience"]:
        p = doc.add_paragraph()
        p.add_run(job["title"]).bold = True
        p.add_run(f"\n{job['company']}").italic = True
        p.add_run(f"\n{job['start']} – {job['end']}").italic = True
        p.add_run(f"\n{job['location']}")
        for bid in job["bullet_ids"]:
            bullet = job["bullets_map"].get(bid, {})
            text = job["rewrites"].get(bid, bullet.get("text", ""))
            bp = doc.add_paragraph(style="List Bullet")
            bp.add_run(text)

    # Educación
    doc.add_heading("Educación", level=1)
    for edu in context["education"]:
        p = doc.add_paragraph()
        p.add_run(edu["degree"]).bold = True
        p.add_run(f"\n{edu['institution']}")
        p.add_run(f"\n{edu['year']}")

    # Certificaciones
    if context["certifications"]:
        doc.add_heading("Certificaciones", level=1)
        for cert in context["certifications"]:
            doc.add_paragraph(cert)

    # Idiomas
    doc.add_heading("Idiomas", level=1)
    for lang in context["languages"]:
        doc.add_paragraph(f"{lang.get('name', '')}: {lang.get('level', '')}")

    doc.save(output_path)
    return output_path
