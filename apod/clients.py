"""HTTP client for NASA's Astronomy Picture of the Day API.

External calls live here rather than in the view so the transport concerns stay
in one place and tests can mock a single seam.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class NasaClientError(Exception):
    """NASA could not be reached, or replied with something unusable."""


class NasaAPODUnavailable(NasaClientError):
    """NASA was reached, but has no entry for the requested date."""


class NasaAPODClient:
    """Fetches a single day's APOD payload.

    The API also supports `start_date`/`end_date`, `count`, and `thumbs`. This
    endpoint serves one date at a time, so only `date` is used.
    """

    def __init__(self, api_key=None, base_url=None, timeout=None, session=None):
        self.api_key = api_key or settings.NASA_API_KEY
        self.base_url = base_url or settings.NASA_API_URL
        self.timeout = timeout if timeout is not None else settings.NASA_API_TIMEOUT
        self.session = session or requests

    def fetch(self, date):
        """Return NASA's raw JSON payload for `date` (a `datetime.date`).

        Raises `NasaAPODUnavailable` when NASA has no entry for the date, and
        `NasaClientError` for every other transport or protocol failure.
        """
        params = {"api_key": self.api_key, "date": date.isoformat()}

        logger.info("Fetching APOD from NASA for %s", date)
        try:
            response = self.session.get(
                self.base_url, params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise NasaClientError(f"Request to NASA failed: {exc}") from exc

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise NasaClientError("NASA returned a non-JSON response.") from exc
            if not isinstance(payload, dict) or "date" not in payload:
                raise NasaClientError(f"Unexpected NASA payload shape: {payload!r}")
            return payload

        # NASA answers with 404, or a 400 whose message says so, for dates it
        # has nothing for -- including today before the daily entry is posted.
        message = self._error_message(response)
        if response.status_code == 404 or (
            response.status_code == 400 and "no data available" in message.lower()
        ):
            raise NasaAPODUnavailable(message or f"No APOD available for {date}.")

        if response.status_code == 429:
            raise NasaClientError(
                "NASA API rate limit exceeded for this key. "
                f"Upstream said: {message or 'no detail provided'}"
            )

        raise NasaClientError(
            f"NASA returned HTTP {response.status_code}: {message or response.text[:200]}"
        )

    @staticmethod
    def _error_message(response):
        """Pull a human-readable message out of an error response, if there is one."""
        try:
            body = response.json()
        except ValueError:
            return ""
        if isinstance(body, dict):
            for key in ("msg", "error_message", "message", "error"):
                value = body.get(key)
                if isinstance(value, str):
                    return value
                if isinstance(value, dict) and isinstance(value.get("message"), str):
                    return value["message"]
        return ""
