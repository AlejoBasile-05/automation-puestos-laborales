"""Tests de verificación ATS (sección 9.4 de AGENTS.md).

Todos los tests usan mocks para evitar llamadas de red reales.
"""

import json
import os

from docx import Document
from docx.shared import Pt
from weasyprint import HTML

from jobradar.ats_check import (
    ats_report_all_passed,
    check_date_formats,
    check_docx_structure,
    check_keyword_coverage,
    check_ligatures,
    check_page_count,
    check_pdf_extractable,
    check_required_sections,
    check_round_trip,
    generate_ats_report,
    save_ats_report,
)

# ---------------------------------------------------------------------------
# Helpers para crear archivos de prueba
# ---------------------------------------------------------------------------

def _make_pdf(tmp_path: str, filename: str, html_content: str) -> str:
    """Crea un PDF de prueba usando WeasyPrint."""
    pdf_path = os.path.join(tmp_path, filename)
    HTML(string=html_content).write_pdf(pdf_path)
    return pdf_path


def _make_docx(tmp_path: str, filename: str, with_table: bool = False,
               contact_in_header: bool = False, empty_body: bool = False) -> str:
    """Crea un DOCX de prueba."""
    doc = Document()
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Arial"
    font.size = Pt(11)

    if contact_in_header:
        header = doc.sections[0].header
        header.add_paragraph("Email: test@example.com")
        header.add_paragraph("Teléfono: 123456789")

    if not empty_body:
        doc.add_heading("Nombre", level=1)
        doc.add_paragraph("Test User")

        doc.add_heading("Contacto", level=1)
        doc.add_paragraph("Email: test@example.com")
        doc.add_paragraph("Teléfono: 123456789")

        doc.add_heading("Resumen", level=1)
        doc.add_paragraph("Test summary")

        doc.add_heading("Habilidades", level=1)
        doc.add_paragraph("Test Skill")

        doc.add_heading("Experiencia profesional", level=1)
        p = doc.add_paragraph()
        p.add_run("Test Job").bold = True
        p.add_run("\nTest Company").italic = True
        p.add_run("\nJan 2020 – Dec 2022").italic = True
        bp = doc.add_paragraph(style="List Bullet")
        bp.add_run("Test bullet point")

        if with_table:
            table = doc.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "Test"
            table.cell(0, 1).text = "Table"

        doc.add_heading("Educación", level=1)
        p = doc.add_paragraph()
        p.add_run("Test Degree").bold = True
        p.add_run("\nTest Institution")
        p.add_run("\nJan 2016 – Dec 2019")

        doc.add_heading("Certificaciones", level=1)
        doc.add_paragraph("Test Certification")

        doc.add_heading("Idiomas", level=1)
        doc.add_paragraph("Test Language: Advanced")

    doc.save(os.path.join(tmp_path, filename))
    return os.path.join(tmp_path, filename)


def test_check_docx_structure_with_table(tmp_path):
    """DOCX con tabla debe fallar el chequeo."""
    path = _make_docx(tmp_path, "test_table.docx", with_table=True)
    result, message = check_docx_structure(path)
    assert not result
    assert "tabla" in message.lower()


def test_check_docx_structure_contact_in_header(tmp_path):
    """DOCX con contacto en encabezado debe fallar."""
    path = _make_docx(tmp_path, "test_header.docx", contact_in_header=True)
    result, message = check_docx_structure(path)
    assert not result
    assert "encabezado" in message.lower()


def test_check_docx_structure_correct(tmp_path):
    """DOCX correcto debe pasar."""
    path = _make_docx(tmp_path, "test_correct.docx")
    result, message = check_docx_structure(path)
    assert result
    assert "correcta" in message


# ---------------------------------------------------------------------------
# Tests de check_pdf_extractable
# ---------------------------------------------------------------------------

def test_check_pdf_extractable_valid(tmp_path):
    """PDF con texto extraíble debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_valid.pdf",
        "<html><body><h1>Nombre</h1><p>Email: test@example.com Teléfono: 123456789</p>"
        "<h2>Experiencia profesional</h2><p>Test Job at Test Company</p>"
        "<h2>Educación</h2><p>Test Degree at Test Institution</p>"
        "<h2>Habilidades</h2><p>Test Skill</p>"
        "<h2>Certificaciones</h2><p>Test Cert</p>"
        "<h2>Idiomas</h2><p>Test Language: Advanced</p>"
        "</body></html>"
    )
    result, message = check_pdf_extractable(pdf_path)
    assert result
    assert "extraíble" in message.lower()


def test_check_pdf_extractable_empty(tmp_path):
    """PDF vacío debe fallar."""
    pdf_path = _make_pdf(tmp_path, "test_empty.pdf", "<html><body></body></html>")
    result, message = check_pdf_extractable(pdf_path)
    assert not result
    assert "vacío" in message.lower() or "vacía" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_required_sections
# ---------------------------------------------------------------------------

def test_check_required_sections_correct(tmp_path):
    """PDF con todas las secciones debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_sections.pdf",
        "<html><body>"
        "<h1>Nombre</h1><p>Test User</p>"
        "<h1>Contacto</h1><p>Email: test@example.com</p>"
        "<h1>Resumen</h1><p>Test summary</p>"
        "<h1>Habilidades</h1><p>Test Skill</p>"
        "<h1>Experiencia profesional</h1><p>Test Job</p>"
        "<h1>Educación</h1><p>Test Degree</p>"
        "<h1>Certificaciones</h2><p>Test Cert</p>"
        "<h1>Idiomas</h1><p>Test Language: Advanced</p>"
        "</body></html>"
    )
    result, message = check_required_sections(pdf_path)
    assert result
    assert "presentes" in message.lower()


def test_check_required_sections_missing(tmp_path):
    """PDF sin alguna sección debe fallar."""
    pdf_path = _make_pdf(
        tmp_path, "test_missing_section.pdf",
        "<html><body><h1>Nombre</h1><p>Test User</p></body></html>"
    )
    result, message = check_required_sections(pdf_path)
    assert not result
    assert "faltantes" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_date_formats
# ---------------------------------------------------------------------------

def test_check_date_formats_correct(tmp_path):
    """PDF con fechas en formato correcto debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_dates.pdf",
        "<html><body>"
        "<p>Jan 2020 – Dec 2022</p>"
        "<p>Mar 2018 – Feb 2020</p>"
        "</body></html>"
    )
    result, message = check_date_formats(pdf_path)
    assert result
    assert "consistente" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_ligatures
# ---------------------------------------------------------------------------

def test_check_ligatures_clean(tmp_path):
    """PDF sin ligaduras rotas debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_ligatures_clean.pdf",
        "<html><body><p>File and flow test</p></body></html>"
    )
    result, message = check_ligatures(pdf_path)
    assert result
    assert "ligaduras" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_page_count
# ---------------------------------------------------------------------------

def test_check_page_count_correct(tmp_path):
    """PDF con pocas páginas debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_pages.pdf",
        "<html><body><p>Contenido corto</p></body></html>"
    )
    result, message = check_page_count(pdf_path, max_pages=2)
    assert result
    assert "dentro del límite" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_keyword_coverage
# ---------------------------------------------------------------------------

def test_check_keyword_coverage_sufficient(tmp_path):
    """PDF con cobertura suficiente debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_coverage.pdf",
        "<html><body><p>Python SQL Django JavaScript</p></body></html>"
    )
    result, message = check_keyword_coverage(pdf_path, ["Python", "SQL", "Django"], 0.90)
    assert result
    assert "cobertura" in message.lower()


# ---------------------------------------------------------------------------
# Tests de check_round_trip
# ---------------------------------------------------------------------------

def test_check_round_trip_correct(tmp_path):
    """PDF con todos los bullets debe pasar."""
    pdf_path = _make_pdf(
        tmp_path, "test_roundtrip.pdf",
        "<html><body><p>Test bullet point</p></body></html>"
    )
    result, message = check_round_trip(pdf_path, ["Test bullet point"])
    assert result
    assert "sin duplicados" in message.lower()


def test_check_round_trip_missing(tmp_path):
    """PDF sin un bullet debe fallar."""
    pdf_path = _make_pdf(
        tmp_path, "test_roundtrip_missing.pdf",
        "<html><body><p>Other content</p></body></html>"
    )
    result, message = check_round_trip(pdf_path, ["Missing bullet"])
    assert not result
    assert "no encontrado" in message.lower()


# ---------------------------------------------------------------------------
# Tests de generate_ats_report y save_ats_report
# ---------------------------------------------------------------------------

def test_generate_ats_report_structure(tmp_path):
    """El reporte debe tener todas las claves esperadas."""
    pdf_path = _make_pdf(
        tmp_path, "test_report.pdf",
        "<html><body><h1>Nombre</h1><p>Email: test@example.com Teléfono: 123456789</p>"
        "<h2>Experiencia profesional</h2><p>Test Job at Test Company Jan 2020 – Dec 2022</p>"
        "<p>Test bullet point</p>"
        "<h2>Educación</h2><p>Test Degree at Test Institution Jan 2016 – Dec 2019</p>"
        "<h2>Habilidades</h2><p>Test Skill</p>"
        "<h2>Certificaciones</h2><p>Test Cert</p>"
        "<h2>Idiomas</h2><p>Test Language: Advanced</p>"
        "</body></html>"
    )
    docx_path = _make_docx(tmp_path, "test_report.docx")

    report = generate_ats_report(
        pdf_path=pdf_path,
        docx_path=docx_path,
        original_bullets=["Test bullet point"],
        keywords=["Python", "SQL"],
        max_pages=2,
        umbral=0.90,
    )

    expected_keys = {
        "pdf_extractable", "reading_order", "contact_info", "required_sections",
        "date_formats", "docx_structure", "ligatures", "page_count",
        "keyword_coverage", "round_trip",
    }
    assert set(report.keys()) == expected_keys
    for value in report.values():
        assert isinstance(value, tuple) and len(value) == 2
        assert isinstance(value[0], bool)
        assert isinstance(value[1], str)


def test_save_ats_report(tmp_path):
    """save_ats_report debe crear un archivo JSON válido."""
    report = {
        "pdf_extractable": [True, "OK"],
        "reading_order": [True, "OK"],
    }
    report_path = save_ats_report(report, tmp_path)
    assert os.path.exists(report_path)
    with open(report_path) as f:
        saved = json.load(f)
    # JSON serializa tuplas como listas
    assert saved == {
        "pdf_extractable": [True, "OK"],
        "reading_order": [True, "OK"],
    }


def test_ats_report_all_passed():
    """ats_report_all_passed debe devolver True si todo pasó."""
    report = {
        "check1": (True, "OK"),
        "check2": (True, "OK"),
    }
    assert ats_report_all_passed(report)

    report_fail = {
        "check1": (True, "OK"),
        "check2": (False, "Failed"),
    }
    assert not ats_report_all_passed(report_fail)
