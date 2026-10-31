"""Cliente HTTP compartido con rate limiting, retry y logging."""

import logging
import time
from typing import Any

import httpx

from jobradar.config import load_config

logger = logging.getLogger(__name__)

# User-Agent identificable
USER_AGENT = "JobRadar/1.0 (+https://github.com/AlejoBasile-05/automation-puestos-laborales)"


# Cargar config global para defaults
_config = load_config()


class HTTPClient:
    """Cliente HTTP síncrono con rate limiting (1 req/s por host), retry con backoff y timeout."""

    def __init__(
        self,
        timeout: float | None = None,
        requests_per_second: float = _config.http.requests_per_second,
    ):
        self.timeout = httpx.Timeout(timeout or _config.http.timeout_seconds)
        self.client = httpx.Client(timeout=self.timeout)
        self.min_interval = 1.0 / requests_per_second
        self._last_request: dict[str, float] = {}

    def _rate_limit(self, host: str) -> None:
        """Enforce 1 request per second per host."""
        now = time.monotonic()
        last = self._last_request.get(host, 0)
        elapsed = now - last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request[host] = time.monotonic()

    def _extract_host(self, url: str) -> str:
        return httpx.URL(url).host or ""

    def _make_request(
        self, method: str, url: str, max_retries: int = 3, **kwargs: Any
    ) -> httpx.Response:
        host = self._extract_host(url)
        self._rate_limit(host)

        headers = kwargs.pop("headers", {})
        headers["User-Agent"] = USER_AGENT

        retry_count = 0
        last_exception: BaseException | None = None

        while retry_count <= max_retries:
            try:
                start = time.monotonic()
                response = self.client.request(method, url, headers=headers, **kwargs)
                duration = time.monotonic() - start

                logger.info(
                    "HTTP %s %s -> %d (%.2fs)",
                    method,
                    url,
                    response.status_code,
                    duration,
                )

                # Retry on 429 or 5xx
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else 2**retry_count
                    logger.warning(
                        "HTTP %s %s -> %d, retrying in %.1fs (attempt %d/%d)",
                        method,
                        url,
                        response.status_code,
                        wait,
                        retry_count + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                    retry_count += 1
                    continue

                return response

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_exception = e
                retry_count += 1
                if retry_count <= max_retries:
                    wait = 2**retry_count
                    logger.warning(
                        "HTTP %s %s error: %s, retrying in %ds (attempt %d/%d)",
                        method,
                        url,
                        e,
                        wait,
                        retry_count,
                        max_retries,
                    )
                    time.sleep(wait)

        logger.error("HTTP %s %s failed after %d retries: %s", method, url, max_retries, last_exception)
        if last_exception:
            raise last_exception from last_exception
        raise RuntimeError(f"HTTP {method} {url} failed after {max_retries} retries") from None

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._make_request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._make_request("POST", url, **kwargs)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HTTPClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
