"""Conector Workday para JobRadar.

Workday es un endpoint interno sin garantías. Si falla, el conector debe
degradar con gracia (log + continuar con las demás fuentes), nunca tumbar
la ingesta.

Referencia: AGENTS.md sección 5 - Fuentes de datos.
"""

from datetime import UTC, datetime
from typing import Any, cast

from jobradar.http_client import HTTPClient
from jobradar.sources.base import JobSource, NormalizedJob


class WorkdaySource(JobSource):
    """Conector para Workday (endpoint interno, inestable por naturaleza)."""

    @property
    def source_name(self) -> str:
        return "workday"

    def _parse_posted_on(self, posted_on: str | None) -> datetime | None:
        """Convierte texto relativo de Workday a datetime aproximado.

        Formatos esperados: "Posted 3 Days Ago", "Posted Today", etc.
        Ante la duda, devuelve None y la fecha se marca como aproximada.
        """
        if not posted_on:
            return None

        text = posted_on.strip().lower()

        try:
            if "today" in text:
                return datetime.now(UTC)
            elif "yesterday" in text:
                from datetime import timedelta

                return datetime.now(UTC) - timedelta(days=1)

            # Extraer número de días: "Posted 3 Days Ago", "Posted 5 Days Ago"
            import re

            match = re.search(r"(\d+)\s+day", text)
            if match:
                from datetime import timedelta

                days = int(match.group(1))
                return datetime.now(UTC) - timedelta(days=days)

            # Formato de fecha absoluta si existe: "2026-10-15"
            match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if match:
                return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC)

        except (ValueError, OSError):
            pass

        return None

    def _normalize_job(
        self,
        job: dict[str, Any],
        company_slug: str,
        company_name: str,
        tenant: str,
        wd: int,
        site: str,
    ) -> NormalizedJob:
        """Normaliza un job de Workday a NormalizedJob.

        Workday devuelve externalPath en el listado. El detalle (descripción
        completa) se obtiene por separado vía GET al endpoint de detalle.
        Aquí normalizamos solo con lo que tenemos en el listado; el detalle
        completo se podría obtener por separado si es necesario.
        """
        external_path = job.get("externalPath", "")
        # Usar el id del raw si está disponible, si no extraer del externalPath
        external_id = str(job.get("id", "")) or external_path.split("/")[-1]
        # Para la URL, usar solo el último segmento del externalPath
        url_path = external_path.split("/")[-1] if external_path else ""

        return NormalizedJob(
            source="workday",
            external_id=external_id,
            company=company_slug,
            company_name=company_name,
            title=job.get("title", ""),
            location=job.get("locationsText"),
            workplace_type=None,  # Workday no provee workplace_type en el listado
            department=None,  # No disponible en el listado
            description_text="",  # Se obtiene por separado si se necesita
            url=f"https://{tenant}.wd{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{url_path}",
            posted_at=self._parse_posted_on(job.get("postedOn")),
            raw=job,
        )

    def _fetch_job_detail(
        self,
        client: HTTPClient,
        tenant: str,
        wd: int,
        site: str,
        external_path: str,
    ) -> dict[str, Any] | None:
        """Obtiene el detalle de una vacante Workday por su externalPath.

        Devuelve None si falla (degradación graceful).
        """
        url = (
            f"https://{tenant}.wd{wd}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}/job/{external_path}"
        )

        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            return cast(dict[str, Any], data)
        except Exception:
            return None

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Workday.

        Workday requiere tenant, wd y site en la configuración.
        Usa POST para el listado y GET para el detalle de cada vacante.
        """
        slug = cast(str, company_config.get("slug"))
        tenant = cast(str, company_config.get("tenant"))
        wd = cast(int, company_config.get("wd"))
        site = cast(str, company_config.get("site"))
        company_name = cast(str, company_config.get("name", slug) or slug)

        if not all([slug, tenant, wd, site]):
            raise ValueError(
                "Workday source requires 'tenant', 'wd', 'site' and 'slug' in company_config"
            )

        base_url = (
            f"https://{tenant}.wd{wd}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}/jobs"
        )

        list_body = {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": "",
        }

        normalized_jobs: list[NormalizedJob] = []

        try:
            with HTTPClient() as client:
                # Petición de listado (POST)
                response = client.post(base_url, json=list_body)
                response.raise_for_status()
                data = cast(dict[str, Any], response.json())

            job_listings = data.get("jobPosts", []) or data.get("jobs", [])

            for job_post in job_listings:
                external_path = str(job_post.get("externalPath", ""))

                # Intentar obtener el detalle de cada vacante (si falla, usamos solo el listado)
                detail = self._fetch_job_detail(client, tenant, wd, site, external_path)
                if detail:
                    # El detalle puede tener más campos; los combinamos
                    merged = {**job_post, **detail}
                else:
                    merged = job_post

                normalized = self._normalize_job(
                    merged, slug, company_name, tenant, wd, site
                )
                normalized_jobs.append(normalized)

        except Exception:
            # Degradación graceful: si Workday falla, no detenemos la ingesta
            # de las demás fuentes. Solo registramos el error y continuamos.
            # El error se reporta al llamador (ingest.py) para que lo registre.
            raise

        return normalized_jobs

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida tenant de Workday y cuenta vacantes."""
        slug = cast(str, company_config.get("slug"))
        tenant = cast(str, company_config.get("tenant"))
        wd = cast(int, company_config.get("wd"))
        site = cast(str, company_config.get("site"))

        if not all([slug, tenant, wd, site]):
            return False, 0, "Missing required Workday config fields"

        base_url = (
            f"https://{tenant}.wd{wd}.myworkdayjobs.com"
            f"/wday/cxs/{tenant}/{site}/jobs"
        )

        list_body = {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": "",
        }

        try:
            with HTTPClient() as client:
                response = client.post(base_url, json=list_body)

            if response.status_code == 404:
                return False, 0, f"Workday tenant '{tenant}' not found (404)"
            response.raise_for_status()

            data = cast(dict[str, Any], response.json())
            job_listings = data.get("jobPosts", []) or data.get("jobs", [])
            count = len(job_listings)
            return True, count, None

        except Exception as e:
            return False, 0, str(e)
