"""Dashboard Streamlit de JobRadar (AGENTS.md sección 10).

Interfaz solamente: toda la consulta y las mutaciones viven en
``jobradar.dashboard_queries``.
"""

from datetime import datetime
from pathlib import Path

import streamlit as st

from jobradar.company_discovery import CompanyDiscoveryClient
from jobradar.config import CompanyConfig, load_config
from jobradar.dashboard_queries import (
    JobFilters,
    export_jobs_to_csv,
    get_all_jobs_with_status,
    get_application_artifacts_query,
    get_application_notes,
    get_filtered_jobs,
    get_job_details,
    get_job_events,
    get_jobs_by_status,
    get_jobs_without_response,
    get_last_visit,
    get_scores_for_jobs,
    mark_job_applied,
    mark_job_discarded,
    mark_job_reviewed,
    run_ingest,
    run_prepare_application,
    run_scoring,
    save_application_message,
    set_application_notes,
    set_last_visit,
)
from jobradar.db.models import JobStatus
from jobradar.ingest import probe_company

st.set_page_config(page_title="JobRadar Dashboard", layout="wide")

if "last_visit" not in st.session_state:
    st.session_state.last_visit = get_last_visit()

STATUS_OPTIONS = ["Todos", *(status.value for status in JobStatus)]


def _normalize_ats_check(outcome: object) -> tuple[bool, str]:
    """Normaliza un chequeo ATS guardado como tupla o lista JSON."""
    if isinstance(outcome, (list, tuple)) and len(outcome) >= 2:
        return bool(outcome[0]), str(outcome[1])
    return False, "Formato de chequeo desconocido"

# ---------------------------------------------------------------------------
# Navegación y filtros
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("JobRadar")
    page = st.radio(
        "Ir a", ["Vacantes", "Seguimiento", "Preparar postulación", "Configuración", "Descubrimiento"]
    )
    st.divider()

    if page == "Vacantes":
        st.subheader("Filtros")
        search_text = st.text_input("Texto de búsqueda")
        company_filter = st.text_input("Empresa")
        source_filter = st.selectbox(
            "Fuente", ["Todos", "Greenhouse", "Lever", "Workday"]
        )
        location_filter = st.text_input("Ubicación")
        remote_filter = st.checkbox("Solo remoto")
        date_from = st.date_input("Fecha desde", value=None)
        date_to = st.date_input("Fecha hasta", value=None)
        status_filter = st.selectbox("Estado", STATUS_OPTIONS)
        only_open = st.checkbox("Solo abiertas", value=True)

        if st.button("Aplicar filtros"):
            st.session_state.last_visit = datetime.now()
            set_last_visit(st.session_state.last_visit)
            st.rerun()

        if st.button("Sincronizar ahora"):
            with st.spinner("Ejecutando ingesta..."):
                st.session_state.ingest_summary = run_ingest()
            st.rerun()

if "ingest_summary" in st.session_state:
    summary = st.session_state.ingest_summary
    st.success(
        f"Ingesta completada: {summary.jobs_new} nuevas, "
        f"{summary.jobs_updated} actualizadas, {summary.jobs_closed} cerradas"
    )
    if summary.errors:
        st.warning(f"{len(summary.errors)} empresas fallaron durante la ingesta")
    del st.session_state.ingest_summary

# ---------------------------------------------------------------------------
# Página: Vacantes
# ---------------------------------------------------------------------------
if page == "Vacantes":
    filters = JobFilters(
        search_text=search_text or None,
        company=company_filter or None,
        source=source_filter.lower() if source_filter != "Todos" else None,
        location=location_filter or None,
        remote=remote_filter,
        date_from=date_from,
        date_to=date_to,
        status=status_filter if status_filter != "Todos" else None,
        only_open=only_open,
    )
    jobs = get_filtered_jobs(filters, st.session_state.last_visit)
    scores = get_scores_for_jobs([job.id for job in jobs])

    st.title("Vacantes")

    if st.button("Puntuar pendientes", key="score-pending"):
        with st.spinner("Puntuando vacantes pendientes..."):
            st.session_state.score_summary = run_scoring()
        st.rerun()

    if "score_summary" in st.session_state:
        score_summary = st.session_state.score_summary
        st.success(
            f"Scoring completado: {score_summary['scored']} puntuadas, "
            f"{score_summary['cached']} en caché, "
            f"{score_summary['errors']} errores "
            f"(límite {score_summary.get('limit', '?')})."
        )
        del st.session_state.score_summary

    if not jobs:
        st.info("No se encontraron vacantes con los filtros actuales")
    else:
        st.dataframe(
            [
                {
                    "ID": job.id,
                    "Título": job.title,
                    "Empresa": job.company.name if job.company else "Desconocida",
                    "Fuente": job.source,
                    "Ubicación": job.location or "N/A",
                    "Fecha": (
                        job.posted_at.strftime("%Y-%m-%d")
                        if job.posted_at
                        else "Desconocida"
                    ),
                    "Puntaje": (
                        f"{scores[job.id]['score']}/100"
                        if job.id in scores
                        else "—"
                    ),
                    "Veredicto": (
                        scores[job.id]["verdict"] if job.id in scores else "—"
                    ),
                    "Estado": "Nueva" if job.is_new else str(job.status),
                }
                for job in jobs
            ],
            hide_index=True,
        )

        for job in jobs:
            with st.expander(f"Detalles de vacante {job.id}: {job.title}"):
                job_details = get_job_details(job.id)
                if job_details is None:
                    st.warning("La vacante ya no existe en la base")
                    continue

                st.write(
                    f"**Empresa:** "
                    f"{job_details.company.name if job_details.company else 'Desconocida'}"
                )
                st.write(f"**Fuente:** {job_details.source}")
                st.write(f"**Ubicación:** {job_details.location or 'N/A'}")
                st.write(
                    f"**Fecha:** "
                    f"{job_details.posted_at.strftime('%Y-%m-%d') if job_details.posted_at else 'Desconocida'}"
                )
                st.write(f"**Estado:** {job_details.status}")
                st.write(f"**URL:** {job_details.url or 'No disponible'}")
                st.subheader("Descripción")
                st.write(job_details.description_text)

                job_score = scores.get(job.id)
                if job_score:
                    st.subheader("Puntuación de compatibilidad")
                    st.metric(
                        "Score",
                        f"{job_score['score']}/100",
                        job_score["verdict"],
                    )
                    for label, values in (
                        ("Coincidencias", job_score["matches"]),
                        ("Brechas", job_score["gaps"]),
                        ("Alertas", job_score["red_flags"]),
                    ):
                        if values:
                            st.write(f"**{label}:**")
                            for item in values:
                                st.write(f"- {item}")
                else:
                    st.caption("Sin puntaje todavía.")

                st.subheader("Historial de eventos")
                events = get_job_events(job.id)
                if events:
                    for event in events:
                        st.write(
                            f"- {event.created_at.strftime('%Y-%m-%d %H:%M')}: "
                            f"{event.type} - {event.payload_json}"
                        )
                else:
                    st.write("No hay eventos registrados")

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Marcar como revisada", key=f"reviewed-{job.id}"):
                        mark_job_reviewed(job.id)
                        st.rerun()
                with col2:
                    if st.button("Marcar como descartada", key=f"discarded-{job.id}"):
                        mark_job_discarded(job.id)
                        st.rerun()
                with col3:
                    if st.button("Marcar como aplicada", key=f"applied-{job.id}"):
                        try:
                            mark_job_applied(job.id)
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Vacante marcada como aplicada")
                            st.rerun()

# ---------------------------------------------------------------------------
# Página: Seguimiento
# ---------------------------------------------------------------------------
elif page == "Seguimiento":
    st.title("Seguimiento de Vacantes")

    status_counts = get_jobs_by_status()
    st.subheader("Conteo por Estado")
    if status_counts:
        columns = st.columns(len(status_counts))
        for column, (status, count) in zip(columns, status_counts.items(), strict=True):
            column.metric(status.capitalize(), count)
    else:
        st.info("Todavía no hay vacantes registradas")

    st.divider()

    tracking_status = st.selectbox(
        "Filtrar por estado", ["Todos", *sorted(status_counts)]
    )
    st.subheader("Lista de Vacantes")
    tracked_jobs = get_all_jobs_with_status(
        None if tracking_status == "Todos" else tracking_status
    )

    if not tracked_jobs:
        st.info("No hay vacantes para este estado")
    else:
        for tracked in tracked_jobs:
            with st.expander(f"{tracked['title']} - {tracked['company']}"):
                st.write(f"**Estado:** {tracked['status']}")
                st.write(f"**Fecha de publicación:** {tracked['posted_at'] or 'N/A'}")
                st.write(f"**Fecha de postulación:** {tracked['applied_at'] or 'N/A'}")

                notes = get_application_notes(tracked["id"])
                new_notes = st.text_area(
                    "Notas", value=notes, key=f"notes_{tracked['id']}"
                )
                if new_notes != notes:
                    set_application_notes(tracked["id"], new_notes)
                    st.success("Notas guardadas")

                if tracked["status"] == JobStatus.APPLIED.value:
                    st.success("Ya está marcada como aplicada")
                elif st.button("Marcar como aplicada", key=f"apply_{tracked['id']}"):
                    try:
                        mark_job_applied(tracked["id"])
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Vacante marcada como aplicada")
                        st.rerun()

    st.divider()
    st.subheader("Exportar Datos")
    if st.button("Exportar a CSV"):
        st.download_button(
            label="Descargar CSV",
            data=export_jobs_to_csv(),
            file_name=f"jobradar_tracking_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

    st.divider()
    st.subheader("Recordatorios")
    days_threshold = st.number_input(
        "Días sin respuesta para recordatorio", value=7, min_value=1
    )
    no_response_jobs = get_jobs_without_response(int(days_threshold))
    if no_response_jobs:
        st.warning(
            f"Hay {len(no_response_jobs)} vacantes sin respuesta tras "
            f"{days_threshold} días"
        )
        for pending in no_response_jobs:
            st.write(
                f"- {pending['title']} - {pending['company']} "
                f"(Aplicada el {pending['applied_at'] or 'N/A'})"
            )
    else:
        st.info("No hay vacantes sin respuesta pendientes")

# ---------------------------------------------------------------------------
# Página: Preparar postulación (Fase 4C)
# ---------------------------------------------------------------------------
elif page == "Preparar postulación":
    st.title("Preparar postulación")

    candidate_jobs = get_filtered_jobs(JobFilters(only_open=True))
    if not candidate_jobs:
        st.info("No hay vacantes abiertas para preparar.")
    else:
        job_options = {
            job.id: (
                f"#{job.id} — {job.title} "
                f"({job.company.name if job.company else 'N/A'})"
            )
            for job in candidate_jobs
        }
        job_id = st.selectbox(
            "Seleccionar vacante",
            options=list(job_options),
            format_func=lambda value: job_options[value],
        )

        job = get_job_details(job_id)
        if job is not None and job.url:
            st.link_button("Abrir enlace de la vacante", job.url)

        if st.button("Preparar CV y mensaje"):
            with st.spinner("Generando CV adaptado y reporte ATS..."):
                result = run_prepare_application(job_id)
            if result.get("exito"):
                st.success(
                    "Postulación preparada en "
                    f"{result.get('output_dir', 'output')} "
                    f"(cobertura requerida {result['required_coverage']:.0%})."
                )
            else:
                st.error(result.get("error", "Error desconocido"))

        app_data = get_application_artifacts_query(job_id)
        if not app_data:
            st.info("Esta vacante todavía no tiene una postulación preparada.")
        else:
            tailored = app_data["tailored"] or {}

            st.subheader("Vista previa del CV adaptado")
            st.write(f"**Headline:** {tailored.get('headline', 'N/A')}")
            st.write(f"**Resumen:** {tailored.get('summary', 'N/A')}")
            st.write(f"**Habilidades:** {', '.join(tailored.get('skills', []))}")
            st.write(
                f"**Keywords usados:** "
                f"{', '.join(tailored.get('keywords_used', []))}"
            )
            for experience in tailored.get("experience", []):
                st.write(
                    f"- {experience.get('experience_id', '')}: "
                    f"{', '.join(experience.get('bullet_ids', []))}"
                )

            st.subheader("Panel ATS")
            st.metric(
                "Cobertura requerida", f"{app_data['required_coverage']:.0%}"
            )
            for check_name, outcome in (app_data.get("ats_report") or {}).items():
                passed, message = _normalize_ats_check(outcome)
                st.write(f"{'✅' if passed else '❌'} **{check_name}**: {message}")

            keywords = app_data.get("keywords") or []
            supported = [kw for kw in keywords if kw.get("status") == "supported"]
            gaps = [kw for kw in keywords if kw.get("status") == "gap"]
            st.write(
                f"**Keywords cubiertas ({len(supported)}):** "
                f"{', '.join(kw.get('term', '') for kw in supported) or '—'}"
            )
            st.write(
                f"**Brechas que no tenés ({len(gaps)}):** "
                f"{', '.join(kw.get('term', '') for kw in gaps) or '—'}"
            )

            knockouts = app_data.get("knockouts") or []
            if knockouts:
                st.write("**Filtros eliminatorios:**")
                for knockout in knockouts:
                    requirement = knockout.get("requirement", "")
                    status = knockout.get("status", "unknown")
                    st.write(f"- {requirement}: **{status}**")
                    if status == "not_met" and knockout.get("mandatory"):
                        st.warning(
                            f"Requisito obligatorio no cumplido: {requirement}"
                        )

            st.subheader("Mensaje de postulación")
            message = st.text_area(
                "Mensaje editable",
                value=app_data.get("message_text", ""),
                height=200,
                key=f"message_{app_data['application_id']}",
            )
            if st.button("Guardar mensaje"):
                save_application_message(app_data["application_id"], message)
                st.success("Mensaje guardado")

            col1, col2 = st.columns(2)
            with col1:
                pdf_path = app_data.get("pdf_path")
                if pdf_path and Path(pdf_path).exists():
                    st.download_button(
                        "Descargar PDF",
                        Path(pdf_path).read_bytes(),
                        file_name=Path(pdf_path).name,
                        mime="application/pdf",
                    )
            with col2:
                docx_path = app_data.get("docx_path")
                if docx_path and Path(docx_path).exists():
                    st.download_button(
                        "Descargar DOCX",
                        Path(docx_path).read_bytes(),
                        file_name=Path(docx_path).name,
                        mime=(
                            "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document"
                        ),
                    )

            st.caption("Copiá el mensaje con el botón de copiar del bloque:")
            st.code(app_data.get("message_text", ""), language="text")

            if st.button("Marcar como aplicada"):
                try:
                    mark_job_applied(job_id)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Vacante marcada como aplicada")
                    st.rerun()

# ---------------------------------------------------------------------------
# Página: Configuración
# ---------------------------------------------------------------------------
elif page == "Configuración":
    st.title("Configuración")
    config = load_config()

    st.subheader("Empresas Configuradas")
    if not config.companies:
        st.info("No hay empresas configuradas. Añádelas en config.yaml.")
    for index, company in enumerate(config.companies):
        with st.expander(f"{company.name} ({company.source})", expanded=False):
            st.text_input("Nombre", value=company.name, key=f"company_name_{index}")
            st.selectbox(
                "Fuente",
                ["greenhouse", "lever", "workday"],
                index=(
                    ["greenhouse", "lever", "workday"].index(company.source)
                    if company.source in ["greenhouse", "lever", "workday"]
                    else 0
                ),
                key=f"company_source_{index}",
            )
            st.text_input(
                "Slug", value=company.slug or "", key=f"company_slug_{index}"
            )
            st.caption(
                "Los cambios en empresas se aplican editando config.yaml y "
                "reiniciando el dashboard."
            )

    st.divider()
    st.subheader("Filtros de Búsqueda")
    st.text_area(
        "Palabras clave incluir (una por línea)",
        value="\n".join(config.search.keywords_include),
        key="keywords_include",
    )
    st.text_area(
        "Palabras clave excluir (una por línea)",
        value="\n".join(config.search.keywords_exclude),
        key="keywords_exclude",
    )
    st.text_area(
        "Ubicaciones (una por línea)",
        value="\n".join(config.search.locations),
        key="locations",
    )
    st.checkbox("Aceptar remoto", value=config.search.accept_remote, key="accept_remote")
    st.number_input(
        "Antigüedad máxima (días)",
        value=config.search.max_age_days,
        min_value=1,
        key="max_age_days",
    )
    st.caption(
        "Los filtros de ingesta se aplican editando config.yaml y reiniciando "
        "el dashboard."
    )

    st.divider()
    st.subheader("Modelo LLM")
    st.write(f"**Proveedor:** {config.llm.provider}")
    st.write(f"**Modelo scoring:** {config.llm.model_scoring}")
    st.write(f"**Modelo escritura:** {config.llm.model_writing}")
    st.write(f"**Máx. vacantes por corrida:** {config.llm.max_jobs_per_run}")
    st.info(
        "La configuración del LLM se lee de config.yaml y .env. Edita esos "
        "archivos para cambios permanentes."
    )

# ---------------------------------------------------------------------------
# Página: Descubrimiento (Fase 7)
# ---------------------------------------------------------------------------
elif page == "Descubrimiento":
    discovery_config = load_config().discovery
    st.title("Descubrimiento de empresas")
    st.caption(
        "Busca portales de Greenhouse, Lever y Workday con el proveedor de "
        "búsqueda configurado. Ninguna empresa se añade automáticamente: copia "
        "el bloque YAML y pégalo en config.yaml."
    )
    st.info(
        f"Proveedor activo: **{discovery_config.provider}** · "
        f"máximo {discovery_config.max_queries_per_run} consultas por corrida · "
        "caché de 24 h. Google CSE tiene 100 consultas gratis por día."
    )

    query = st.text_input(
        "Consulta de búsqueda",
        placeholder='site:boards.greenhouse.io "analista financiero" Monterrey',
    )
    limit = st.slider("Máximo de resultados", min_value=1, max_value=20, value=10)

    if st.button("Buscar empresas"):
        try:
            client = CompanyDiscoveryClient(config=discovery_config)
            candidates = client.discover_companies(query, limit)
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
            candidates = []

        rows = []
        with st.spinner("Validando portales con probe..."):
            for candidate in candidates:
                ok, count, error = probe_company(
                    CompanyConfig(
                        name=candidate["company_name"],
                        source=candidate["source"],
                        slug=candidate["slug"],
                    )
                )
                rows.append(
                    {
                        "Empresa": candidate["company_name"],
                        "Fuente": candidate["source"],
                        "Slug": candidate["slug"],
                        "Vacantes": count if ok else f"? ({error})",
                        "URL": candidate["url"],
                    }
                )
        st.session_state.discovery_rows = rows

    discovery_rows = st.session_state.get("discovery_rows", [])
    if not discovery_rows:
        st.info("Todavía no buscaste empresas.")
    else:
        st.dataframe(discovery_rows, hide_index=True)
        chosen_slug = st.selectbox(
            "Empresa para añadir", [row["Slug"] for row in discovery_rows]
        )
        selected = next(
            row for row in discovery_rows if row["Slug"] == chosen_slug
        )
        st.code(
            f'  - name: "{selected["Empresa"]}"\n'
            f'    source: "{selected["Fuente"]}"\n'
            f'    slug: "{selected["Slug"]}"',
            language="yaml",
        )
        if selected["Fuente"] == "workday":
            st.info(
                "Workday además requiere 'tenant', 'wd' y 'site' en config.yaml."
            )

else:
    st.error("Página no encontrada")
