"""Wikipedia provider: search, extract, and every way it can come up empty."""

import requests

from apod.models import APOD, SupplementalInfo
from apod.providers import WikipediaProvider

from .base import SAMPLE_DATE, NoNetworkTestCase
from .fixtures import (
    WIKIPEDIA_EMPTY_SEARCH_RESPONSE,
    WIKIPEDIA_EXTRACT_RESPONSE,
    WIKIPEDIA_SEARCH_RESPONSE,
)


class FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


class ScriptedSession:
    """Returns queued responses in order, one per call."""

    def __init__(self, responses=None, exception=None):
        self.responses = list(responses or [])
        self.exception = exception
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append(params)
        if self.exception is not None:
            raise self.exception
        return self.responses.pop(0)


class WikipediaProviderTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.apod = APOD.objects.create(
            date=SAMPLE_DATE,
            title="Witness XZ Andromedae Wink",
            explanation="...",
            media_type="video",
            url="https://apod.nasa.gov/apod/image/2609/xz_and.mp4",
            raw_response={},
        )

    def provider(self, **kwargs):
        session = ScriptedSession(**kwargs)
        return WikipediaProvider(session=session), session

    def test_searches_on_the_editorial_title_then_fetches_the_extract(self):
        provider, session = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_EXTRACT_RESPONSE),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "XZ Andromedae")
        self.assertEqual(result.url, "https://en.wikipedia.org/wiki/XZ_Andromedae")
        self.assertIn("eclipsing binary", result.extract)

        # The search step carries the full APOD title, prose and all.
        self.assertEqual(session.calls[0]["srsearch"], "Witness XZ Andromedae Wink")
        self.assertEqual(session.calls[0]["list"], "search")
        self.assertEqual(session.calls[1]["titles"], "XZ Andromedae")

    def test_falls_back_to_an_or_query_when_the_full_title_misses(self):
        """MediaWiki ANDs terms, so an editorial title alone returns nothing."""
        provider, session = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_EMPTY_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_EXTRACT_RESPONSE),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "XZ Andromedae")
        self.assertEqual(session.calls[0]["srsearch"], "Witness XZ Andromedae Wink")
        self.assertEqual(
            session.calls[1]["srsearch"], "Witness OR XZ OR Andromedae OR Wink"
        )

    def test_falls_back_to_the_segment_before_a_colon(self):
        """APOD's "Subject: editorial phrase" form names its subject first."""
        self.apod.title = "IC 1795: The Fishhead Nebula"
        provider, session = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_EMPTY_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_EXTRACT_RESPONSE),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(session.calls[1]["srsearch"], "IC 1795")

    def test_candidate_queries_are_ordered_and_deduplicated(self):
        provider, _ = self.provider()

        self.assertEqual(
            list(provider._candidate_queries("IC 1795: The Fishhead Nebula")),
            [
                "IC 1795: The Fishhead Nebula",
                "IC 1795",
                "IC OR 1795 OR The OR Fishhead OR Nebula",
            ],
        )
        # A single term collapses every strategy into the same query.
        self.assertEqual(list(provider._candidate_queries("Andromeda")), ["Andromeda"])

    def test_no_search_results_anywhere_in_the_cascade_is_not_found(self):
        provider, session = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_EMPTY_SEARCH_RESPONSE),
                FakeResponse(WIKIPEDIA_EMPTY_SEARCH_RESPONSE),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)
        self.assertIn("No Wikipedia search results", result.reason)
        self.assertEqual(len(session.calls), 2)

    def test_missing_page_is_not_found(self):
        provider, _ = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_SEARCH_RESPONSE),
                FakeResponse({"query": {"pages": {"-1": {"pageid": -1, "missing": ""}}}}),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)

    def test_empty_extract_is_not_found(self):
        page = dict(WIKIPEDIA_EXTRACT_RESPONSE["query"]["pages"]["12345"], extract="  ")
        provider, _ = self.provider(
            responses=[
                FakeResponse(WIKIPEDIA_SEARCH_RESPONSE),
                FakeResponse({"query": {"pages": {"12345": page}}}),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)
        self.assertIn("no intro extract", result.reason)

    def test_network_failure_is_an_error_result_not_an_exception(self):
        provider, _ = self.provider(exception=requests.Timeout("timed out"))
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.ERROR)
        self.assertIn("timed out", result.reason)

    def test_http_error_is_an_error_result(self):
        provider, _ = self.provider(responses=[FakeResponse({}, status_code=500)])
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.ERROR)

    def test_apod_without_a_title_is_not_found(self):
        self.apod.title = ""
        provider, session = self.provider()
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)
        self.assertEqual(session.calls, [])
