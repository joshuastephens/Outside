"""Endpoint behaviour: caching, defaults, validation, and graceful degradation.

All external HTTP is mocked. `NoNetworkTestCase` additionally blocks the
underlying transport, so an un-mocked call fails the test rather than silently
reaching the real NASA or Wikipedia APIs.
"""

import contextlib
import datetime
from unittest import mock

from apod.clients import NasaAPODUnavailable, NasaClientError
from apod.models import APOD, SupplementalInfo
from apod.providers import SupplementalResult
from apod.services import today

from .base import SAMPLE_DATE, NoNetworkTestCase
from .fixtures import MINIMAL_PAYLOAD, image_payload


@contextlib.contextmanager
def stub_nasa(payload=None, side_effect=None):
    """Replace the NASA client the service layer builds with a stub."""
    client = mock.Mock()
    client.fetch = mock.Mock(return_value=payload, side_effect=side_effect)
    with mock.patch("apod.services.NasaAPODClient", return_value=client):
        yield client


@contextlib.contextmanager
def stub_provider(result=None, side_effect=None, source="wikipedia"):
    """Replace the supplemental provider with a stub."""
    provider = mock.Mock()
    provider.source = source
    provider.fetch = mock.Mock(return_value=result, side_effect=side_effect)
    with mock.patch("apod.services.get_default_provider", return_value=provider):
        yield provider


def found_result(source="wikipedia"):
    return SupplementalResult(
        source=source,
        status=SupplementalInfo.Status.FOUND,
        matched_title="Messier 101",
        url="https://en.wikipedia.org/wiki/Messier_101",
        extract="Messier 101 is a face-on spiral galaxy.",
        raw_response={"query": {}},
    )


class CacheHitTests(NoNetworkTestCase):
    """(1) A stored date is served from the database, with no NASA call."""

    def setUp(self):
        super().setUp()
        self.apod = APOD.objects.create(
            date=SAMPLE_DATE,
            title="Messier 101",
            explanation="A spiral galaxy seen nearly face-on.",
            media_type="image",
            url="https://apod.nasa.gov/apod/image/2405/galaxy.jpg",
            hdurl="https://apod.nasa.gov/apod/image/2405/galaxy_hd.jpg",
            copyright="Some Astrophotographer",
            raw_response=image_payload(),
        )
        SupplementalInfo.objects.create(
            apod=self.apod,
            source="wikipedia",
            status=SupplementalInfo.Status.FOUND,
            matched_title="Messier 101",
            url="https://en.wikipedia.org/wiki/Messier_101",
            extract="Messier 101 is a face-on spiral galaxy.",
        )

    def test_served_from_database_without_calling_nasa(self):
        with stub_nasa(payload=image_payload()) as client, stub_provider() as provider:
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 200)
        client.fetch.assert_not_called()
        provider.fetch.assert_not_called()

        body = response.json()
        self.assertEqual(body["date"], SAMPLE_DATE.isoformat())
        self.assertEqual(body["title"], "Messier 101")
        self.assertEqual(body["supplemental"][0]["matched_title"], "Messier 101")

    def test_repeated_requests_do_not_duplicate_rows(self):
        with stub_nasa(payload=image_payload()), stub_provider():
            self.get_apod(SAMPLE_DATE.isoformat())
            self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(APOD.objects.count(), 1)


class CacheMissTests(NoNetworkTestCase):
    """(2) An unknown date is fetched from NASA once, persisted, then returned."""

    def test_fetches_persists_and_returns(self):
        payload = image_payload()

        with stub_nasa(payload=payload) as client, stub_provider(found_result()):
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 200)
        client.fetch.assert_called_once_with(SAMPLE_DATE)

        apod = APOD.objects.get(date=SAMPLE_DATE)
        self.assertEqual(apod.title, "Messier 101")
        self.assertEqual(apod.media_type, "image")
        self.assertEqual(apod.raw_response, payload)

        body = response.json()
        self.assertEqual(body["date"], SAMPLE_DATE.isoformat())
        self.assertEqual(body["url"], payload["url"])
        self.assertEqual(body["hdurl"], payload["hdurl"])
        self.assertEqual(body["copyright"], payload["copyright"])
        self.assertEqual(body["supplemental"][0]["status"], "found")

    def test_second_request_is_a_cache_hit(self):
        with stub_nasa(payload=image_payload()) as client, stub_provider(found_result()):
            self.get_apod(SAMPLE_DATE.isoformat())
            self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(client.fetch.call_count, 1)

    def test_missing_optional_fields_are_stored_as_null(self):
        """NASA omits `copyright` and `hdurl` on many days."""
        payload = dict(MINIMAL_PAYLOAD)
        date = datetime.date.fromisoformat(payload["date"])

        with stub_nasa(payload=payload), stub_provider(found_result()):
            response = self.get_apod(date.isoformat())

        self.assertEqual(response.status_code, 200)
        apod = APOD.objects.get(date=date)
        self.assertIsNone(apod.hdurl)
        self.assertIsNone(apod.copyright)
        self.assertEqual(response.json()["media_type"], "video")


class DefaultDateTests(NoNetworkTestCase):
    """(3) Omitting `date` requests today."""

    def test_no_date_param_uses_today(self):
        current = today()
        payload = image_payload(date=current.isoformat())

        with stub_nasa(payload=payload) as client, stub_provider(found_result()):
            response = self.get_apod()

        self.assertEqual(response.status_code, 200)
        client.fetch.assert_called_once_with(current)
        self.assertEqual(response.json()["date"], current.isoformat())

    def test_empty_date_param_also_uses_today(self):
        current = today()

        with stub_nasa(payload=image_payload(date=current.isoformat())) as client:
            with stub_provider(found_result()):
                response = self.get_apod("")

        self.assertEqual(response.status_code, 200)
        client.fetch.assert_called_once_with(current)

    def test_today_is_anchored_to_apods_publishing_timezone(self):
        """UTC rolls over hours before APOD does; "today" must follow APOD."""
        import datetime as dt

        from apod.services import APOD_TIMEZONE

        eastern_now = dt.datetime.now(APOD_TIMEZONE)
        self.assertEqual(today(), eastern_now.date())


class MalformedDateTests(NoNetworkTestCase):
    """(4) An unparseable `date` is a 400, and never reaches NASA."""

    def test_malformed_dates_return_400(self):
        for value in ["not-a-date", "05/01/2024", "2024-13-45", "2024-05", "20240501"]:
            with self.subTest(value=value):
                with stub_nasa(payload=image_payload()) as client:
                    response = self.get_apod(value)

                self.assertEqual(response.status_code, 400)
                self.assertIn("YYYY-MM-DD", response.json()["detail"])
                client.fetch.assert_not_called()
                self.assertEqual(APOD.objects.count(), 0)


class DateRangeTests(NoNetworkTestCase):
    """(5) Dates outside APOD's range fail cleanly rather than as a 500."""

    def test_date_before_first_apod_returns_400(self):
        with stub_nasa(payload=image_payload()) as client:
            response = self.get_apod("1995-06-15")

        self.assertEqual(response.status_code, 400)
        self.assertIn("1995-06-16", response.json()["detail"])
        client.fetch.assert_not_called()

    def test_first_apod_date_itself_is_accepted(self):
        with stub_nasa(payload=image_payload(date="1995-06-16")) as client:
            with stub_provider(found_result()):
                response = self.get_apod("1995-06-16")

        self.assertEqual(response.status_code, 200)
        client.fetch.assert_called_once_with(datetime.date(1995, 6, 16))

    def test_future_date_returns_400(self):
        future = today() + datetime.timedelta(days=1)

        with stub_nasa(payload=image_payload()) as client:
            response = self.get_apod(future.isoformat())

        self.assertEqual(response.status_code, 400)
        self.assertIn("future", response.json()["detail"])
        client.fetch.assert_not_called()

    def test_date_nasa_has_no_entry_for_returns_404(self):
        """A valid date NASA has not published yet -- a 404, not a 500."""
        with stub_nasa(side_effect=NasaAPODUnavailable("No data available for date.")):
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 404)
        self.assertIn("No data available", response.json()["detail"])
        self.assertEqual(APOD.objects.count(), 0)

    def test_nasa_transport_failure_returns_502(self):
        with stub_nasa(side_effect=NasaClientError("connection reset")):
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 502)
        self.assertIn("connection reset", response.json()["detail"])


class SupplementalFailureTests(NoNetworkTestCase):
    """(6) A failed supplemental lookup never breaks the endpoint."""

    def test_provider_error_still_returns_nasa_data(self):
        error = SupplementalResult.error("wikipedia", "Request failed: timeout")

        with stub_nasa(payload=image_payload()), stub_provider(error):
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["title"], "Messier 101")

        supplemental = body["supplemental"][0]
        self.assertEqual(supplemental["status"], "error")
        self.assertIsNone(supplemental["matched_title"])
        self.assertIsNone(supplemental["url"])
        self.assertEqual(supplemental["extract"], "")
        self.assertIn("timeout", supplemental["reason"])

    def test_provider_raising_unexpectedly_still_returns_nasa_data(self):
        with stub_nasa(payload=image_payload()):
            with stub_provider(side_effect=RuntimeError("provider exploded")):
                response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Messier 101")

        info = SupplementalInfo.objects.get(apod__date=SAMPLE_DATE)
        self.assertEqual(info.status, SupplementalInfo.Status.ERROR)
        self.assertIn("provider exploded", info.reason)

    def test_no_wikipedia_match_is_recorded_as_not_found(self):
        miss = SupplementalResult.not_found("wikipedia", "No Wikipedia search results.")

        with stub_nasa(payload=image_payload()), stub_provider(miss):
            response = self.get_apod(SAMPLE_DATE.isoformat())

        self.assertEqual(response.status_code, 200)
        supplemental = response.json()["supplemental"][0]
        self.assertEqual(supplemental["status"], "not_found")
        self.assertEqual(supplemental["extract"], "")
        self.assertIn("No Wikipedia search results", supplemental["reason"])
