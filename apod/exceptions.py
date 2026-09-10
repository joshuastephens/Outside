"""API-facing exceptions.

Each maps a specific failure to a deliberate status code so callers never see a
bare 500 for a condition we already understand.
"""

from rest_framework.exceptions import APIException


class InvalidAPODDate(APIException):
    """The requested date is malformed or outside the range APOD covers."""

    status_code = 400
    default_detail = "Invalid date."
    default_code = "invalid_date"


class APODNotAvailable(APIException):
    """A valid date that NASA has no entry for (e.g. today, pre-publication)."""

    status_code = 404
    default_detail = "No Astronomy Picture of the Day is available for that date."
    default_code = "apod_not_available"


class UpstreamServiceError(APIException):
    """NASA was unreachable, slow, rate-limited, or returned something unusable."""

    status_code = 502
    default_detail = "The upstream NASA API could not be reached. Please try again."
    default_code = "upstream_error"
