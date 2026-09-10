"""Application service layer.

Everything the endpoint does lives here so that any presentation layer -- the
API view today, a server-rendered template page later -- calls the same
function rather than making an HTTP request back to this application.
"""

import datetime
import logging
import zoneinfo

from django.conf import settings

from .clients import NasaAPODClient, NasaAPODUnavailable, NasaClientError
from .exceptions import APODNotAvailable, InvalidAPODDate, UpstreamServiceError
from .models import FIRST_APOD_DATE, APOD, SupplementalInfo
from .providers import SupplementalResult, get_default_provider

logger = logging.getLogger(__name__)

DATE_FORMAT = "%Y-%m-%d"

# APOD is published on US Eastern time, and NASA interprets the `date` param the
# same way. Anchoring here rather than to UTC avoids a stretch of every evening
# where UTC has already rolled over and "today" would 404.
APOD_TIMEZONE = zoneinfo.ZoneInfo("America/New_York")


def today():
    """The current APOD date, in APOD's own timezone."""
    return datetime.datetime.now(APOD_TIMEZONE).date()


def parse_date_param(raw):
    """Turn a `?date=` query value into a validated `datetime.date`.

    An absent or empty value means today. Anything unparseable or outside the
    range APOD covers raises `InvalidAPODDate` (HTTP 400).
    """
    if raw is None or raw == "":
        return today()

    try:
        parsed = datetime.datetime.strptime(raw.strip(), DATE_FORMAT).date()
    except (ValueError, AttributeError):
        raise InvalidAPODDate(
            f"Could not parse date {raw!r}. Expected format YYYY-MM-DD."
        )

    validate_apod_date(parsed)
    return parsed


def validate_apod_date(date):
    """Reject dates NASA is guaranteed to refuse, before spending a request."""
    if date < FIRST_APOD_DATE:
        raise InvalidAPODDate(
            f"{date.isoformat()} is before the first Astronomy Picture of the Day "
            f"({FIRST_APOD_DATE.isoformat()})."
        )
    current = today()
    if date > current:
        raise InvalidAPODDate(
            f"{date.isoformat()} is in the future; the latest available date is "
            f"{current.isoformat()}."
        )
    return date


def get_apod_for_date(date):
    """Return the `APOD` for `date`, fetching and persisting it on a cache miss.

    Database first: a stored row is served without touching NASA at all. Only a
    miss triggers the upstream call, and the result is persisted (together with
    best-effort supplemental data) before it is returned.
    """
    validate_apod_date(date)

    existing = (
        APOD.objects.prefetch_related("supplemental").filter(date=date).first()
    )
    if existing is not None:
        logger.info("Cache hit for %s; serving from database", date)
        return existing

    logger.info("Cache miss for %s; calling NASA", date)
    try:
        payload = NasaAPODClient().fetch(date)
    except NasaAPODUnavailable as exc:
        raise APODNotAvailable(str(exc)) from exc
    except NasaClientError as exc:
        logger.error("NASA fetch failed for %s: %s", date, exc)
        raise UpstreamServiceError(
            f"Could not retrieve the Astronomy Picture of the Day for "
            f"{date.isoformat()}: {exc}"
        ) from exc

    apod = _persist_apod(date, payload)
    _attach_supplemental(apod)
    return apod


def _persist_apod(requested_date, payload):
    """Store NASA's payload, normalizing the fields the API contract exposes."""
    stored_date = _payload_date(payload) or requested_date

    apod, _created = APOD.objects.update_or_create(
        date=stored_date,
        defaults={
            "title": payload.get("title") or "",
            "explanation": payload.get("explanation") or "",
            "media_type": payload.get("media_type") or "",
            "url": payload.get("url") or "",
            # Absent on many days -- stored as NULL rather than assumed.
            "hdurl": payload.get("hdurl") or None,
            "copyright": (payload.get("copyright") or "").strip() or None,
            "raw_response": payload,
        },
    )
    return apod


def _payload_date(payload):
    try:
        return datetime.datetime.strptime(payload.get("date", ""), DATE_FORMAT).date()
    except (ValueError, TypeError):
        return None


def _attach_supplemental(apod, provider=None):
    """Enrich `apod` in place, swallowing every failure.

    Supplemental data is a bonus, not a dependency: if the provider is
    unreachable or finds nothing, a row recording why is stored and the APOD is
    returned regardless.
    """
    if not settings.SUPPLEMENTAL_ENABLED:
        return None

    provider = provider or get_default_provider()
    try:
        result = provider.fetch(apod)
    except Exception as exc:  # noqa: BLE001 -- enrichment must never break the endpoint
        logger.exception("Supplemental provider raised for %s", apod.date)
        result = SupplementalResult.error(
            getattr(provider, "source", "unknown"), f"Provider raised: {exc}"
        )

    try:
        info, _created = SupplementalInfo.objects.update_or_create(
            apod=apod,
            source=result.source,
            defaults={
                "status": result.status,
                "matched_title": result.matched_title,
                "url": result.url,
                "extract": result.extract or "",
                "reason": result.reason or "",
                "raw_response": result.raw_response or {},
            },
        )
    except Exception:  # noqa: BLE001 -- ditto for the write
        logger.exception("Could not persist supplemental info for %s", apod.date)
        return None

    # The instance may already have a cached `supplemental` prefetch.
    if hasattr(apod, "_prefetched_objects_cache"):
        apod._prefetched_objects_cache.pop("supplemental", None)
    return info
