"""CLI de JobRadar — comandos: probe, ingest, score, requirements, tailor, ats-check, dashboard."""

from datetime import UTC, datetime
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from jobradar.ats_check import ats_report_all_passed, generate_ats_report, save_ats_report
from jobradar.ats_keywords import ensure_requirements, match_keywords
from jobradar.company_discovery import CompanyDiscoveryClient
from jobradar.config import CompanyConfig, Settings, load_config
from jobradar.db.models import Application, Event, Job, JobStatus
from jobradar.db.session import get_engine, get_session_factory, init_db
from jobradar.ingest import ingest_companies, probe_company
from jobradar.knockouts import check_knockouts
from jobradar.llm.factory import create_llm_client
from jobradar.render.docx import generate_docx
from jobradar.render.pdf import generate_pdf
from jobradar.scoring import score_pending
from jobradar.tailoring import tailor_job

load_dotenv()  # Carga variables de entorno desde .env

app = typer.Typer(help="JobRadar: radar local de vacantes + CV a la medida")
console = Console()

PROMPT_VERSION = "scoring_v1"
CV_MASTER_PATH = Path("data/cv_master.yaml")


def _get_session():
    engine = get_engine()
    init_db(engine)
    return get_session_factory(engine)


def _build_llm(config: Settings):
    """Crea el cliente LLM con el proveedor y modelo de config.yaml."""
    return create_llm_client(
        provider=config.llm.provider,
        model=config.llm.model_scoring,
    )


@app.command()
def probe(source: str, slug: str):
    """Valida si un slug existe y cuántas vacantes devuelve."""
    config = load_config()
    company = None
    for c in config.companies:
        if c.source == source and c.slug == slug:
            company = c
            break
    if company is None:
        # Crear una empresa temporal para hacer probe
        company = CompanyConfig(name=slug, source=source, slug=slug)

    ok, count, error = probe_company(company)
    if ok:
        console.print(f"[green]OK:[/green] {source} - {slug}: {count} vacantes")
    else:
        console.print(f"[red]ERROR:[/red] {source} - {slug}: {error}")


@app.command()
def ingest():
    """Descarga y guarda vacantes de todas las empresas configuradas."""
    config = load_config()
    session_factory = _get_session()
    summary = ingest_companies(config.companies, session_factory=session_factory)

    console.print("\n[bold]Ingesta completada:[/bold]")
    console.print(f"  Empresas procesadas: {summary.companies_processed}")
    console.print(f"  Vacantes nuevas: {summary.jobs_new}")
    console.print(f"  Vacantes actualizadas: {summary.jobs_updated}")
    console.print(f"  Vacantes cerradas: {summary.jobs_closed}")
    if summary.errors:
        console.print("\n[red]Errores:[/red]")
        for e in summary.errors:
            console.print(f"  - {e.company_name} ({e.source}): {e.error_message}")


@app.command()
def score(
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-l",
        help=(
            "Máximo de vacantes a puntuar. Si se omite se usa "
            "llm.max_jobs_per_run; un valor mayor se recorta a ese tope."
        ),
    ),
):
    """Punta la compatibilidad de vacantes pendientes contra el CV maestro."""
    if not CV_MASTER_PATH.exists():
        console.print(f"[red]ERROR:[/red] No se encontró {CV_MASTER_PATH}. Crea tu CV maestro primero.")
        raise typer.Exit(1)

    config = load_config()

    try:
        result = score_pending(
            limit=limit,
            provider=config.llm.provider,
            model=config.llm.model_scoring,
        )
    except ValueError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1) from e

    console.print("\n[bold]Scoring completado:[/bold]")
    console.print(f"  Límite aplicado: {result.get('limit', '?')}")
    console.print(f"  Vacantes evaluadas: {result['scored']}")
    console.print(f"  En caché (omitidas): {result['cached']}")
    console.print(f"  Errores: {result['errors']}")
    console.print(f"  Total revisadas: {result['total']}")


@app.command()
def requirements(
    job_id: int = typer.Option(..., "--job-id", help="ID de la vacante"),
):
    """Muestra keywords (supported/gap) y knockouts de una vacante."""
    if not CV_MASTER_PATH.exists():
        console.print(f"[red]ERROR:[/red] No se encontró {CV_MASTER_PATH}. Crea tu CV maestro primero.")
        raise typer.Exit(1)

    session_factory = _get_session()
    config = load_config()

    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            console.print(f"[red]ERROR:[/red] No se encontró la vacante con ID {job_id}")
            raise typer.Exit(1)

        console.print(f"\n[bold]Requisitos de la vacante #{job_id}: {job.title}[/bold]")
        console.print(f"Empresa: {job.company.name if job.company else 'Desconocida'}")
        console.print(f"Fuente: {job.source}")
        console.print(f"URL: {job.url}\n")

        # Extraer requisitos de la descripción (LLM, cacheado por hash)
        try:
            extraction = ensure_requirements(job, session_factory, _build_llm(config))
        except (RuntimeError, ValueError) as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(1) from exc

        keywords = extraction.get("keywords", [])
        knockouts = extraction.get("knockouts", [])

        # Matching determinista de keywords contra CV maestro
        keyword_results = match_keywords(keywords, str(CV_MASTER_PATH))

        # Check de knockouts contra CV maestro
        knockout_results = check_knockouts(knockouts, str(CV_MASTER_PATH))

        # Mostrar keywords
        console.print("[bold]Keywords:[/bold]")
        if not keyword_results:
            console.print("  (no se extrajeron keywords)")
        else:
            supported = [r for r in keyword_results if r["status"] == "supported"]
            gaps = [r for r in keyword_results if r["status"] == "gap"]

            console.print(f"  [green]Cubiertas ({len(supported)}):[/green]")
            for r in supported:
                ev = ", ".join(r["evidence_ids"]) if r["evidence_ids"] else "(sin evidencia específica)"
                console.print(f"    ✓ {r['term']} (evidencia: {ev})")

            console.print(f"  [red]Brechas ({len(gaps)}):[/red]")
            for r in gaps:
                console.print(f"    ✗ {r['term']}")

        # Mostrar knockouts
        console.print("\n[bold]Filtros eliminatorios (knockouts):[/bold]")
        if not knockout_results:
            console.print("  (no se extrajeron knockouts)")
        else:
            met = [r for r in knockout_results if r["status"] == "met"]
            not_met = [r for r in knockout_results if r["status"] == "not_met"]
            unknown = [r for r in knockout_results if r["status"] == "unknown"]

            if met:
                console.print(f"  [green]Cumplidos ({len(met)}):[/green]")
                for r in met:
                    console.print(f"    ✓ {r['requirement']}")

            if not_met:
                console.print(f"  [red]No cumplidos ({len(not_met)}):[/red]")
                for r in not_met:
                    console.print(f"    ✗ {r['requirement']}")

            if unknown:
                console.print(f"  [yellow]Desconocidos ({len(unknown)}):[/yellow]")
                for r in unknown:
                    console.print(f"    ? {r['requirement']}")


@app.command()
def tailor(
    job_id: int = typer.Option(..., "--job-id", help="ID de la vacante"),
):
    """Genera CV adaptado + mensaje para una vacante."""
    if not CV_MASTER_PATH.exists():
        console.print(f"[red]ERROR:[/red] No se encontró {CV_MASTER_PATH}. Crea tu CV maestro primero.")
        raise typer.Exit(1)

    session_factory = _get_session()
    config = load_config()

    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            console.print(f"[red]ERROR:[/red] No se encontró la vacante con ID {job_id}")
            raise typer.Exit(1)

        console.print(f"\n[bold]Generando CV para vacante #{job_id}: {job.title}[/bold]")

        # Extraer requisitos de la descripción (LLM, cacheado por hash)
        try:
            extraction = ensure_requirements(job, session_factory, _build_llm(config))
        except (RuntimeError, ValueError) as exc:
            console.print(f"[red]ERROR:[/red] {exc}")
            raise typer.Exit(1) from exc

        keywords = extraction.get("keywords", [])
        knockouts = extraction.get("knockouts", [])

        # Matching determinista de keywords contra CV maestro
        keyword_results = match_keywords(keywords, str(CV_MASTER_PATH))

        # Check de knockouts contra CV maestro
        knockout_results = check_knockouts(knockouts, str(CV_MASTER_PATH))

        # Solo keywords supported van al LLM
        supported_keywords = [r for r in keyword_results if r["status"] == "supported"]

        console.print(f"  Keywords supported: {len(supported_keywords)}")
        console.print(f"  Keywords gap: {len([r for r in keyword_results if r['status'] == 'gap'])}")

        # Llamar a tailoring
        result = tailor_job(
            job_id=job_id,
            keywords_supported=supported_keywords,
            knockouts=knockout_results,
        )

        if result["exito"]:
            console.print("\n[green]✓ CV generado exitosamente[/green]")
            console.print(f"  Application ID: {result['application_id']}")
            console.print(f"  Required coverage: {result['required_coverage']:.1%}")
            console.print(f"  Overall coverage: {result['overall_coverage']:.1%}")
            console.print(f"\n  Headline: {result['tailored']['headline']}")
            console.print(f"  Summary: {result['tailored']['summary']}")
            console.print(f"  Mensaje: {result['tailored']['cover_message']}")
        else:
            console.print(f"\n[red]✗ Error generando CV:[/red] {result['error']}")
            raise typer.Exit(1)


@app.command()
def mark_reviewed(job_id: int):
    """Marca una vacante como revisada y registra el evento."""
    session_factory = _get_session()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            console.print(f"[red]ERROR:[/red] No se encontró la vacante con ID {job_id}")
            raise typer.Exit(1)

        old_status = job.status
        job.status = JobStatus.REVIEWED
        event = Event(
            job_id=job_id,
            type="status_change",
            payload_json={"old": str(old_status), "new": "reviewed"},
        )
        session.add(event)
        session.commit()
        console.print(f"[green]✓ Vacante #{job_id} marcada como revisada[/green]")


@app.command()
def mark_discarded(job_id: int):
    """Marca una vacante como descartada y registra el evento."""
    session_factory = _get_session()
    with session_factory() as session:
        job = session.get(Job, job_id)
        if job is None:
            console.print(f"[red]ERROR:[/red] No se encontró la vacante con ID {job_id}")
            raise typer.Exit(1)

        old_status = job.status
        job.status = JobStatus.DISCARDED
        event = Event(
            job_id=job_id,
            type="status_change",
            payload_json={"old": str(old_status), "new": "discarded"},
        )
        session.add(event)
        session.commit()
        console.print(f"[green]✓ Vacante #{job_id} marcada como descartada[/green]")


@app.command()
def mark_applied(job_id: int):
    """Marca una vacante como aplicada y guarda la fecha de postulación."""
    session_factory = _get_session()
    with session_factory() as session:
        # Verificar que no exista ya una aplicación
        existing_app = session.get(Application, job_id)
        if existing_app is not None:
            console.print(
                f"[red]ERROR:[/red] Ya existe una aplicación para la vacante #{job_id}"
            )
            raise typer.Exit(1)

        job = session.get(Job, job_id)
        if job is None:
            console.print(f"[red]ERROR:[/red] No se encontró la vacante con ID {job_id}")
            raise typer.Exit(1)

        old_status = job.status
        job.status = JobStatus.APPLIED
        now = datetime.now(UTC)

        new_app = Application(
            job_id=job_id,
            tailored_cv_json={},
            message_text="",
            language="es",
            required_coverage=0.0,
            applied_at=now,
        )
        session.add(new_app)

        event = Event(
            job_id=job_id,
            type="status_change",
            payload_json={"old": str(old_status), "new": "applied"},
        )
        session.add(event)
        session.commit()
        console.print(f"[green]✓ Vacante #{job_id} marcada como aplicada[/green]")


@app.command()
def ats_check(
    job_id: int = typer.Option(..., "--job-id", help="ID de la vacante"),
):
    """Verifica el PDF/DOCX generado contra checklist ATS."""
    if not CV_MASTER_PATH.exists():
        console.print(f"[red]ERROR:[/red] No se encontró {CV_MASTER_PATH}. Crea tu CV maestro primero.")
        raise typer.Exit(1)

    config = load_config()
    session_factory = _get_session()

    with session_factory() as session:
        app = session.get(Application, job_id)
        if app is None:
            console.print(f"[red]ERROR:[/red] No se encontró la aplicación con ID {job_id}")
            raise typer.Exit(1)

        tailored = app.tailored_cv_json
        if not tailored:
            console.print(f"[red]ERROR:[/red] La aplicación {job_id} no tiene CV adaptado.")
            raise typer.Exit(1)

        console.print(f"\n[bold]Verificación ATS para aplicación #{job_id}[/bold]")

        # Generar PDF y DOCX si no existen
        output_dir = f"output/{app.job.company.slug}_{app.job.title}_{datetime.now(UTC).strftime('%Y%m%d')}"
        output_dir = output_dir.replace(" ", "_").replace("/", "_")

        pdf_path = app.pdf_path
        docx_path = app.docx_path

        if not pdf_path:
            pdf_path = generate_pdf(tailored, output_dir)
            app.pdf_path = pdf_path
        if not docx_path:
            docx_path = generate_docx(tailored, output_dir)
            app.docx_path = docx_path

        # Recopilar bullets originales para el check de ida y vuelta
        original_bullets = []
        for exp in tailored.get("experience", []):
            for bid in exp.get("bullet_ids", []):
                rewrite = exp.get("rewrites", {}).get(bid, "")
                if rewrite:
                    original_bullets.append(rewrite)

        keywords = tailored.get("keywords_used", [])

        # Ejecutar ATS check
        report = generate_ats_report(
            pdf_path=pdf_path,
            docx_path=docx_path,
            original_bullets=original_bullets,
            keywords=keywords,
            max_pages=config.ats.max_pages,
            umbral=config.ats.min_required_coverage,
        )

        # Guardar reporte
        report_path = save_ats_report(report, output_dir)
        app.ats_report_json = report
        session.commit()

        # Mostrar resultados
        all_passed = ats_report_all_passed(report)
        for check_name, (passed, message) in report.items():
            status = "[green]✓[/green]" if passed else "[red]✗[/red]"
            console.print(f"  {status} {check_name}: {message}")

        console.print(f"\n[bold]Reporte guardado en:[/bold] {report_path}")
        if all_passed:
            console.print("\n[green]✓ Todas las verificaciones ATS pasaron[/green]")
        else:
            console.print("\n[red]✗ Algunas verificaciones ATS fallaron[/red]")
            raise typer.Exit(1)


@app.command()
def dashboard():
    """Abre el dashboard de Streamlit."""
    import subprocess
    import sys
    dashboard_path = Path(__file__).parent.parent.parent / "app" / "dashboard.py"
    if not dashboard_path.exists():
        console.print(f"[red]ERROR:[/red] No se encontró {dashboard_path}")
        raise typer.Exit(1)
    console.print(f"[bold]Iniciando dashboard en {dashboard_path}[/bold]")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


@app.command()
def discover(query: str, limit: int = typer.Option(10, "--limit", "-l", help="Máximo de resultados a devolver")):
    """Descubre nuevas empresas de reclutamiento mediante búsqueda web.

    Busca portales de Greenhouse, Lever y Workday en una consulta de búsqueda
    y muestra los slugs encontrados para que el usuario decida cuáles añadir
    a config.yaml. Nunca añade empresas automáticamente.
    """
    config = load_config()
    console.print(f"\n[bold]Buscando empresas:[/bold] {query}")
    console.print(
        f"Proveedor: {config.discovery.provider} | Límite: {limit} resultados "
        f"(máx. {config.discovery.max_queries_per_run} consultas por corrida)\n"
    )

    try:
        client = CompanyDiscoveryClient(config=config.discovery)
        results = client.discover_companies(query, limit)
    except ValueError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1) from e
    except RuntimeError as e:
        console.print(f"[red]ERROR:[/red] {e}")
        raise typer.Exit(1) from e

    if not results:
        console.print("[yellow]No se encontraron empresas de reclutamiento.[/yellow]")
        return

    console.print(f"\n[bold]Empresas encontradas:[/bold] {len(results)}\n")

    # Tabla de resultados
    console.print(f"{'#':<4} {'Empresa':<30} {'Fuente':<12} {'Slug':<30} {'Vacantes':<10}")
    console.print("-" * 90)

    for i, result in enumerate(results, 1):
        slug = result["slug"]
        source = result["source"]
        company_name = result.get("company_name", slug)

        # Validar con probe para obtener conteo de vacantes
        try:
            probe_config = CompanyConfig(
                name=company_name,
                source=source,
                slug=slug,
            )
            ok, count, error = probe_company(probe_config)
            if ok:
                vacantes = str(count)
            else:
                vacantes = f"? ({error})"
        except Exception:
            vacantes = "?"

        console.print(f"{i:<4} {company_name:<30} {source:<12} {slug:<30} {vacantes:<10}")

    console.print("\n[yellow]Nota:[/yellow] Ninguna empresa se ha añadido a config.yaml todavía.")
    console.print("Para añadir una empresa, edite config.yaml manualmente o use el dashboard.")
    console.print("\nEjemplo de configuración en config.yaml:")
    console.print("  companies:")
    console.print("    - name: \"Nombre Empresa\"")
    console.print("      source: greenhouse")
    console.print("      slug: tu-slug")


if __name__ == "__main__":
    app()
