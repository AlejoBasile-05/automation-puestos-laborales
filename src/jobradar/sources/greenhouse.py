"""Conector Greenhouse."""

import html
import re
from datetime import datetime
from typing import Any

from jobradar.http_client import HTTPClient
from jobradar.sources.base import JobSource, NormalizedJob


class GreenhouseSource(JobSource):
    """Conector para Greenhouse."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    @property
    def source_name(self) -> str:
        return "greenhouse"

    def _clean_html(self, html_text: str) -> str:
        """Convierte HTML escapado a texto plano limpio."""
        if not html_text:
            return ""

        # Primero unescape de entidades HTML
        text = html.unescape(html_text)

        # Reemplazar tags de bloque con saltos de línea
        text = re.sub(r"</?(p|div|br|li|ul|ol|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)

        # Reemplazar tags de formato inline con espacios
        text = re.sub(r"</?(strong|b|em|i|u|span)[^>]*>", " ", text, flags=re.IGNORECASE)

        # Eliminar cualquier tag restante
        text = re.sub(r"<[^>]+>", "", text)

        # Limpiar entidades HTML restantes
        text = html.unescape(text)

        # Normalizar whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = text.strip()

        return text

    def _parse_datetime(self, dt_str: str | None) -> datetime | None:
        """Parsea datetime ISO 8601 de Greenhouse."""
        if not dt_str:
            return None
        try:
            # Greenhouse usa formato ISO con timezone offset
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _normalize_job(self, job: dict[str, Any], company_slug: str, company_name: str) -> NormalizedJob:
        """Normaliza un job de Greenhouse a NormalizedJob."""
        # Preferir first_published como fecha de publicación original
        posted_at = self._parse_datetime(job.get("first_published"))
        if posted_at is None:
            posted_at = self._parse_datetime(job.get("updated_at"))

        # Ubicación
        location = job.get("location", {}).get("name") if job.get("location") else None

        # Departamento
        department = None
        if job.get("departments") and len(job["departments"]) > 0:
            department = job["departments"][0].get("name")

        # Workplace type - Greenhouse no lo da explícitamente, inferir de location
        workplace_type = None
        if location and "remote" in location.lower():
            workplace_type = "remote"

        return NormalizedJob(
            source="greenhouse",
            external_id=str(job["id"]),
            company=company_slug,
            company_name=company_name,
            title=job.get("title", ""),
            location=location,
            workplace_type=workplace_type,
            department=department,
            description_text=self._clean_html(job.get("content", "")),
            url=job.get("absolute_url", ""),
            posted_at=posted_at,
            raw=job,
        )

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Greenhouse."""
        slug = company_config.get("slug")
        if not slug:
            raise ValueError("Greenhouse source requires 'slug' in company_config")

        company_name = company_config.get("name", slug) or slug

        url = f"{self.BASE_URL}/{slug}/jobs?content=true"

        with HTTPClient() as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        jobs = data.get("jobs", [])
        return [self._normalize_job(job, slug, company_name) for job in jobs]

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida slug de Greenhouse y cuenta vacantes."""
        slug = company_config.get("slug")
        if not slug:
            return False, 0, "Missing 'slug' in company_config"

        url = f"{self.BASE_URL}/{slug}/jobs?content=true"

        try:
            with HTTPClient() as client:
                response = client.get(url)

            if response.status_code == 404:
                return False, 0, f"Board '{slug}' not found (404)"
            response.raise_for_status()

            data = response.json()
            count = len(data.get("jobs", []))
            return True, count, None

        except Exception as e:
            return False, 0, str(e)
