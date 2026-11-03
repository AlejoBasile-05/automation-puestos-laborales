"""Conector Ashby.

Ashby expone un job board público por empresa:
``GET https://api.ashbyhq.com/posting-api/job-board/{slug}``
La respuesta trae ``{"jobs": [...], "apiVersion": ...}``.
"""

import html
import re
from datetime import datetime
from typing import Any

from jobradar.http_client import HTTPClient
from jobradar.sources.base import JobSource, NormalizedJob

_WORKPLACE_TYPES = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
}


class AshbySource(JobSource):
    """Conector para Ashby."""

    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    @property
    def source_name(self) -> str:
        return "ashby"

    def _clean_html(self, html_text: str) -> str:
        """Convierte HTML a texto plano limpio."""
        if not html_text:
            return ""
        text = html.unescape(html_text)
        text = re.sub(r"</?(p|div|br|li|ul|ol|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?(strong|b|em|i|u|span)[^>]*>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _parse_datetime(self, dt_str: str | None) -> datetime | None:
        """Parsea un ISO 8601 de Ashby (``publishedAt``)."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _get_workplace_type(self, job: dict[str, Any]) -> str | None:
        """Normaliza ``workplaceType``; si falta, usa ``isRemote``."""
        raw = job.get("workplaceType")
        if isinstance(raw, str):
            normalized = _WORKPLACE_TYPES.get(raw.strip().lower())
            if normalized:
                return normalized
        if job.get("isRemote") is True:
            return "remote"
        return None

    def _normalize_job(
        self, job: dict[str, Any], company_slug: str, company_name: str
    ) -> NormalizedJob:
        """Normaliza un job de Ashby a ``NormalizedJob``."""
        description = job.get("descriptionPlain") or self._clean_html(
            job.get("descriptionHtml", "")
        )

        return NormalizedJob(
            source="ashby",
            external_id=str(job.get("id", "")),
            company=company_slug,
            company_name=company_name,
            title=job.get("title", ""),
            location=job.get("location") or None,
            workplace_type=self._get_workplace_type(job),
            department=job.get("department") or job.get("team"),
            description_text=description.strip() if description else "",
            url=job.get("jobUrl") or job.get("applyUrl", ""),
            posted_at=self._parse_datetime(job.get("publishedAt")),
            raw=job,
        )

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene las vacantes publicadas de un board de Ashby."""
        slug = company_config.get("slug")
        if not slug:
            raise ValueError("Ashby source requires 'slug' in company_config")

        company_name = company_config.get("name", slug) or slug
        url = f"{self.BASE_URL}/{slug}"

        with HTTPClient() as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        jobs = [job for job in data.get("jobs", []) if job.get("isListed", True)]
        return [self._normalize_job(job, slug, company_name) for job in jobs]

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida el slug de Ashby y cuenta vacantes publicadas."""
        slug = company_config.get("slug")
        if not slug:
            return False, 0, "Missing 'slug' in company_config"

        url = f"{self.BASE_URL}/{slug}"

        try:
            with HTTPClient() as client:
                response = client.get(url)

            if response.status_code == 404:
                return False, 0, f"Board '{slug}' not found (404)"
            response.raise_for_status()

            data = response.json()
            count = sum(1 for job in data.get("jobs", []) if job.get("isListed", True))
            return True, count, None

        except Exception as e:  # noqa: BLE001
            return False, 0, str(e)
