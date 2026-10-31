"""CLI principal de JobRadar."""

import typer
from rich.console import Console

from jobradar import __version__
from jobradar.sources import get_source, list_sources

app = typer.Typer(
    name="jobradar",
    help="Radar local de vacantes + CV a la medida para ATS",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    """Muestra la versión y sale."""
    if value:
        console.print(f"jobradar v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Muestra la versión y sale",
    ),
) -> None:
    """JobRadar: radar local de vacantes + CV a la medida para ATS."""
    pass


@app.command()
def probe(
    source: str = typer.Argument(..., help="Fuente: greenhouse | lever | workday"),
    slug: str = typer.Argument(..., help="Slug/tenant de la empresa"),
) -> None:
    """Valida una empresa y cuenta sus vacantes."""
    # Validar fuente
    available = list_sources()
    if source.lower() not in available:
        console.print(f"[red]Fuente desconocida: {source}[/red]")
        console.print(f"Fuentes disponibles: {', '.join(available)}")
        raise typer.Exit(1)

    try:
        source_instance = get_source(source)
        # company_config para probe
        company_config = {"slug": slug, "name": slug}

        console.print(f"[blue]Probando {source} con slug '{slug}'...[/blue]")
        success, count, error = source_instance.probe(company_config)

        if success:
            console.print(f"[green]✓[/green] {source}/{slug}: {count} vacantes encontradas")
        else:
            console.print(f"[red]✗[/red] {source}/{slug}: {error}")
            raise typer.Exit(1) from None

    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error inesperado:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def ingest() -> None:
    """Descarga y guarda vacantes de todas las empresas configuradas."""
    console.print("[yellow]ingest no implementado aún[/yellow]")


@app.command()
def score(
    limit: int = typer.Option(20, "--limit", "-l", help="Máximo de vacantes a puntuar"),
) -> None:
    """Puntúa vacantes pendientes contra el CV maestro."""
    console.print(f"[yellow]score no implementado aún[/yellow] (limit={limit})")


@app.command()
def requirements(job_id: int = typer.Argument(..., help="ID de la vacante")) -> None:
    """Muestra keywords (supported/gap) y knockouts de una vacante."""
    console.print(f"[yellow]requirements no implementado aún[/yellow] (job_id={job_id})")


@app.command()
def tailor(job_id: int = typer.Argument(..., help="ID de la vacante")) -> None:
    """Genera CV adaptado + mensaje para una vacante."""
    console.print(f"[yellow]tailor no implementado aún[/yellow] (job_id={job_id})")


@app.command()
def ats_check(job_id: int = typer.Argument(..., help="ID de la vacante")) -> None:
    """Verifica el PDF/DOCX generado contra checklist ATS."""
    console.print(f"[yellow]ats-check no implementado aún[/yellow] (job_id={job_id})")


if __name__ == "__main__":
    app()
