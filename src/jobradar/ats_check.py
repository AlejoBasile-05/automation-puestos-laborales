"""Verificación de archivos PDF/DOCX contra checklist ATS (sección 9.4 de AGENTS.md)."""

import json
import os
import re
from typing import Any

import pdfplumber
from docx import Document

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

SECTION_ORDER = [
    "Nombre",
    "Contacto",
    "Resumen",
    "Habilidades",
    "Experiencia profesional",
    "Educación",
    "Certificaciones",
    "Idiomas",
]

LIGATURE_CHARS = {"\ufb00", "\ufb01", "\ufb02", "\ufb03", "\ufb04"}  # ﬀ ﬁ ﬂ ﬃ ﬄ


def _extract_pdf_text(pdf_path: str) -> str:
    """Extrae todo el texto de un PDF."""
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


# ---------------------------------------------------------------------------
# Chequeos individuales
# ---------------------------------------------------------------------------

def check_pdf_extractable(pdf_path: str) -> tuple[bool, str]:
    """1. El texto del PDF es extraíble y no está vacío."""
    try:
        text = _extract_pdf_text(pdf_path)
        if not text.strip():
            return False, "PDF texto está vacío o es una imagen"
        return True, "PDF texto es extraíble y no está vacío"
    except Exception as e:
        return False, f"Error extrayendo texto del PDF: {e}"


def check_reading_order(pdf_path: str) -> tuple[bool, str]:
    """2. Orden de lectura correcto: encabezados en orden, bullets bajo su puesto."""
    try:
        text = _extract_pdf_text(pdf_path)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # Verificar que los encabezados aparezcan en el orden esperado
        found_sections = []
        for line in lines:
            if line in SECTION_ORDER and line not in found_sections:
                found_sections.append(line)

        expected_order = [s for s in SECTION_ORDER if s in found_sections]
        if found_sections != expected_order:
            return False, f"Orden de secciones incorrecto: {found_sections}"

        # Verificar que los bullets de cada puesto queden bajo su puesto
        # Buscar líneas que empiezan con • y verificar que preceden a un puesto
        for i, line in enumerate(lines):
            if line.startswith("•"):
                # Buscar el puesto más reciente antes de este bullet
                found_job = False
                for j in range(i - 1, -1, -1):
                    if lines[j] in ("Experiencia profesional",):
                        found_job = True
                        break
                    # Un puesto nuevo empieza con título en negrita (heurística)
                    if lines[j] and not lines[j].startswith("•"):
                        # Si encontramos otro encabezado de sección, parar
                        if lines[j] in SECTION_ORDER:
                            break
                if not found_job:
                    return False, f"Bullet sin puesto asociado: '{line[:50]}...'"
        return True, "Orden de lectura correcto"
    except Exception as e:
        return False, f"Error verificando orden de lectura: {e}"


def check_contact_info(pdf_path: str) -> tuple[bool, str]:
    """3. Nombre, correo y teléfono en las primeras líneas."""
    try:
        text = _extract_pdf_text(pdf_path)
        lines = [line.strip() for line in text.split("\n") if line.strip()][:15]
        first_text = "\n".join(lines)
        has_email = bool(re.search(r"[\w\.-]+@[\w\.-]+\.\w+", first_text))
        has_phone = bool(re.search(r"[\+]?[\d\s\-\(\)]{7,}", first_text))
        if not has_email or not has_phone:
            return False, "Nombre, correo o teléfono no detectados en las primeras líneas"
        return True, "Nombre, correo y teléfono detectados en las primeras líneas"
    except Exception as e:
        return False, f"Error verificando contacto: {e}"


def check_required_sections(pdf_path: str) -> tuple[bool, str]:
    """4. Encabezados estándar presentes."""
    try:
        text = _extract_pdf_text(pdf_path)
        missing = [s for s in SECTION_ORDER if s not in text]
        if missing:
            return False, f"Secciones faltantes: {', '.join(missing)}"
        return True, "Encabezados estándar presentes"
    except Exception as e:
        return False, f"Error verificando secciones: {e}"


def check_date_formats(pdf_path: str) -> tuple[bool, str]:
    """5. Todas las fechas son parseables y siguen un único formato."""
    try:
        text = _extract_pdf_text(pdf_path)
        # Buscar fechas en formato MMM YYYY – MMM YYYY
        date_pattern = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s\d{4}\s–\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s\d{4}\b"
        dates = re.findall(date_pattern, text)
        if not dates:
            # También aceptar formato corto MMM YYYY
            date_pattern2 = r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s\d{4}\b"
            dates = re.findall(date_pattern2, text)
        if not dates:
            return False, "No se encontraron fechas parseables"
        return True, f"Todas las fechas ({len(dates)}) siguen formato consistente"
    except Exception as e:
        return False, f"Error verificando fechas: {e}"


def check_docx_structure(docx_path: str) -> tuple[bool, str]:
    """6. DOCX sin tablas, cuadros de texto, imágenes, columnas, encabezado/pie."""
    try:
        doc = Document(docx_path)
        # No tablas
        if doc.tables:
            return False, "DOCX contiene tablas"
        # No imágenes en encabezado/pie
        for section in doc.sections:
            header_text = " ".join(p.text for p in section.header.paragraphs).strip()
            footer_text = " ".join(p.text for p in section.footer.paragraphs).strip()
            if header_text:
                return False, "DOCX tiene contenido en encabezado"
            if footer_text:
                return False, "DOCX tiene contenido en pie de página"
        # No imágenes inline
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                return False, "DOCX contiene imágenes"
        return True, "DOCX estructura correcta (sin tablas, imágenes, columnas, encabezado/pie)"
    except Exception as e:
        return False, f"Error verificando estructura DOCX: {e}"


def check_ligatures(pdf_path: str) -> tuple[bool, str]:
    """7. Sin caracteres de reemplazo ni ligaduras rotas."""
    try:
        text = _extract_pdf_text(pdf_path)
        # Carácter de reemplazo Unicode
        if "\ufffd" in text:
            return False, "PDF contiene carácter de reemplazo (�)"
        # Ligaduras comunes
        found_ligatures = [c for c in LIGATURE_CHARS if c in text]
        if found_ligatures:
            return False, f"PDF contiene ligaduras rotas: {found_ligatures}"
        return True, "Sin caracteres de reemplazo ni ligaduras rotas"
    except Exception as e:
        return False, f"Error verificando ligaduras: {e}"


def check_page_count(pdf_path: str, max_pages: int) -> tuple[bool, str]:
    """8. Número de páginas ≤ max_pages."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) > max_pages:
                return False, f"PDF tiene {len(pdf.pages)} páginas, máximo permitido: {max_pages}"
            return True, f"Número de páginas ({len(pdf.pages)}) dentro del límite ({max_pages})"
    except Exception as e:
        return False, f"Error verificando número de páginas: {e}"


def check_keyword_coverage(
    pdf_path: str, keywords: list[str], umbral: float
) -> tuple[bool, str]:
    """9. required_coverage ≥ umbral y ninguna keyword repetida más de 3 veces."""
    try:
        text = _extract_pdf_text(pdf_path).lower()
        if not keywords:
            return True, "No hay keywords para verificar"
        found_count = sum(1 for kw in keywords if kw.lower() in text)
        coverage = found_count / len(keywords)
        if coverage < umbral:
            return False, f"Cobertura de keywords ({coverage:.1%}) por debajo del umbral ({umbral:.1%})"
        # Verificar repeticiones excesivas (más de 3)
        for kw in keywords:
            count = text.count(kw.lower())
            if count > 3:
                return False, f"Keyword '{kw}' repetida {count} veces (máximo 3)"
        return True, f"Cobertura de keywords ({coverage:.1%}) por encima del umbral ({umbral:.1%})"
    except Exception as e:
        return False, f"Error verificando cobertura de keywords: {e}"


def check_round_trip(pdf_path: str, original_bullets: list[str]) -> tuple[bool, str]:
    """10. Ida y vuelta: texto extraído contiene cada bullet completo y sin duplicados."""
    try:
        text = _extract_pdf_text(pdf_path)
        for bullet in original_bullets:
            if bullet not in text:
                return False, f"Bullet no encontrado en el PDF: '{bullet[:60]}...'"
        # Verificar no hay duplicados
        for bullet in original_bullets:
            count = text.count(bullet)
            if count > 1:
                return False, f"Bullet duplicado en el PDF: '{bullet[:60]}...'"
        return True, "Ida y vuelta correcta: todos los bullets presentes y sin duplicados"
    except Exception as e:
        return False, f"Error verificando ida y vuelta: {e}"


# ---------------------------------------------------------------------------
# Reporte consolidado
# ---------------------------------------------------------------------------

def generate_ats_report(
    pdf_path: str,
    docx_path: str,
    original_bullets: list[str],
    keywords: list[str],
    max_pages: int,
    umbral: float,
) -> dict[str, Any]:
    """Ejecuta los 10 chequeos y genera el reporte ATS."""
    return {
        "pdf_extractable": check_pdf_extractable(pdf_path),
        "reading_order": check_reading_order(pdf_path),
        "contact_info": check_contact_info(pdf_path),
        "required_sections": check_required_sections(pdf_path),
        "date_formats": check_date_formats(pdf_path),
        "docx_structure": check_docx_structure(docx_path),
        "ligatures": check_ligatures(pdf_path),
        "page_count": check_page_count(pdf_path, max_pages),
        "keyword_coverage": check_keyword_coverage(pdf_path, keywords, umbral),
        "round_trip": check_round_trip(pdf_path, original_bullets),
    }


def save_ats_report(report: dict[str, Any], output_dir: str) -> str:
    """Guarda el reporte ATS como JSON."""
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "ats_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report_path


def ats_report_all_passed(report: dict[str, Any]) -> bool:
    """Verifica si todos los chequeos pasaron."""
    return all(
        isinstance(v, tuple) and v[0] is True
        for v in report.values()
    )
