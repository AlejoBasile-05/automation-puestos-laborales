"""Conector Lever."""

from datetime import UTC, datetime
from typing import Any

from jobradar.http_client import HTTPClient
from jobradar.sources.base import JobSource, NormalizedJob


class LeverSource(JobSource):
    """Conector para Lever."""

    BASE_URL = "https://api.lever.co/v0/postings"

    @property
    def source_name(self) -> str:
        return "lever"

    def _parse_datetime(self, timestamp_ms: int | None) -> datetime | None:
        """Convierte epoch milliseconds a datetime UTC."""
        if timestamp_ms is None:
            return None
        try:
            return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        except (ValueError, OSError):
            return None

    def _get_workplace_type(self, job: dict[str, Any]) -> str | None:
        """Determina workplace_type desde los datos de Lever."""
        # workplaceType puede ser: "remote", "onsite", "hybrid"
        wt = job.get("workplaceType")
        if isinstance(wt, str) and wt in ("remote", "onsite", "hybrid"):
            return wt

        # Fallback: inferir desde location
        location = job.get("categories", {}).get("location", "")
        if location and "remote" in location.lower():
            return "remote"
        return None

    def _normalize_job(self, job: dict[str, Any], company_slug: str, company_name: str) -> NormalizedJob:
        """Normaliza un job de Lever a NormalizedJob."""
        categories = job.get("categories", {})

        # Usar descriptionPlain (texto plano) en preferencia a description (HTML)
        description = job.get("descriptionPlain") or job.get("descriptionBodyPlain") or ""

        return NormalizedJob(
            source="lever",
            external_id=job.get("id", ""),
            company=company_slug,
            company_name=company_name,
            title=job.get("text", ""),
            location=categories.get("location"),
            workplace_type=self._get_workplace_type(job),
            department=categories.get("department") or categories.get("team"),
            description_text=description.strip() if description else "",
            url=job.get("hostedUrl") or job.get("applyUrl", ""),
            posted_at=self._parse_datetime(job.get("createdAt")),
            raw=job,
        )

    def fetch_jobs(self, company_config: dict[str, Any]) -> list[NormalizedJob]:
        """Obtiene vacantes de Lever."""
        slug = company_config.get("slug")
        if not slug:
            raise ValueError("Lever source requires 'slug' in company_config")

        company_name = company_config.get("name", slug) or slug

        url = f"{self.BASE_URL}/{slug}?mode=json"

        with HTTPClient() as client:
            response = client.get(url)
            response.raise_for_status()
            jobs = response.json()

        return [self._normalize_job(job, slug, company_name) for job in jobs]

    def probe(self, company_config: dict[str, Any]) -> tuple[bool, int, str | None]:
        """Valida slug de Lever y cuenta vacantes."""
        slug = company_config.get("slug")
        if not slug:
            return False, 0, "Missing 'slug' in company_config"

        url = f"{self.BASE_URL}/{slug}?mode=json"

        try:
            with HTTPClient() as client:
                response = client.get(url)

            if response.status_code == 404:
                return False, 0, f"Company '{slug}' not found (404)"
            response.raise_for_status()

            jobs = response.json()
            count = len(jobs)
            return True, count, None

        except Exception as e:
            return False, 0, str(e)
