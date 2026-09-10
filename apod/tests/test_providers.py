"""Wikipedia provider: search, extract, and every way it can come up empty."""

import requests

from apod.models import APOD, SupplementalInfo
from apod.providers import WikipediaProvider

from .base import SAMPLE_DATE, NoNetworkTestCase
from .fixtures import (
    BAD_MATCH_CANDIDATES,
    WIKIPEDIA_EMPTY_SEARCH_RESPONSE,
    WIKIPEDIA_EXTRACT_RESPONSE,
    WIKIPEDIA_SEARCH_RESPONSE,
    extract_response,
    search_response,
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
                FakeResponse(search_response("Fish Head Nebula", "Heart and Soul Nebula")),
                FakeResponse(
                    extract_response("Fish Head Nebula", "The Fish Head Nebula is...")
                ),
            ]
        )
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "Fish Head Nebula")
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
        with self.assertLogs("apod.providers", level="WARNING") as captured:
            result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.ERROR)
        self.assertIn("timed out", result.reason)
        self.assertIn("Wikipedia lookup failed", captured.records[0].getMessage())

    def test_http_error_is_an_error_result(self):
        provider, _ = self.provider(responses=[FakeResponse({}, status_code=500)])
        with self.assertLogs("apod.providers", level="WARNING") as captured:
            result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.ERROR)
        self.assertIn("Wikipedia lookup failed", captured.records[0].getMessage())

    def test_apod_without_a_title_is_not_found(self):
        self.apod.title = ""
        provider, session = self.provider()
        result = provider.fetch(self.apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)
        self.assertEqual(session.calls, [])


class CandidateScoringTests(NoNetworkTestCase):
    """Scoring, not MediaWiki's ranking, decides which candidate is accepted.

    Each case here is a real APOD title paired with the candidates live
    MediaWiki actually returns for it.
    """

    def make_apod(self, title, explanation="", date=SAMPLE_DATE):
        return APOD.objects.create(
            date=date,
            title=title,
            explanation=explanation,
            media_type="image",
            url="https://apod.nasa.gov/apod/image/x.jpg",
            raw_response={},
        )

    def provider(self, **kwargs):
        session = ScriptedSession(**kwargs)
        return WikipediaProvider(session=session), session

    def test_requests_enough_candidates_to_choose_between(self):
        apod = self.make_apod("Saturn at Night")
        provider, session = self.provider(
            responses=[
                FakeResponse(search_response("Saturn")),
                FakeResponse(extract_response("Saturn", "Saturn is the sixth planet.")),
            ]
        )
        provider.fetch(apod)

        self.assertEqual(session.calls[0]["srlimit"], 5)

    def test_rejects_every_candidate_when_none_scores_well_enough(self):
        """The unscored cascade confidently returned *Mono Lake* here."""
        apod = self.make_apod(
            "Pink Aurora over Crater Lake",
            "A rare pink aurora glows above Crater Lake in Oregon.",
        )
        candidates = BAD_MATCH_CANDIDATES["Pink Aurora over Crater Lake"]
        provider, session = self.provider(
            responses=[
                FakeResponse(search_response(*candidates)),
                FakeResponse(search_response(*candidates)),
            ]
        )
        result = provider.fetch(apod)

        self.assertEqual(result.status, SupplementalInfo.Status.NOT_FOUND)
        self.assertIsNone(result.matched_title)
        self.assertIsNone(result.url)
        self.assertEqual(result.extract, "")
        # The miss names the closest candidate and its score, so it is diagnosable.
        self.assertIn("Mono Lake", result.reason)
        self.assertIn("0.50", result.reason)
        # No extract was ever requested.
        self.assertTrue(all("titles" not in call for call in session.calls))

    def test_picks_the_best_scoring_candidate_not_the_first(self):
        """*Saturn* is third in MediaWiki's ranking and still the right answer."""
        apod = self.make_apod(
            "Saturn at Night", "Cassini looks back at the night side of Saturn."
        )
        provider, session = self.provider(
            responses=[
                FakeResponse(
                    search_response(
                        "Perry Saturn",
                        "Night Warriors: Darkstalkers' Revenge",
                        "Saturn",
                        "Night Striker",
                        "Saturn V",
                    )
                ),
                FakeResponse(
                    extract_response("Saturn", "Saturn is the sixth planet from the Sun.")
                ),
            ]
        )
        result = provider.fetch(apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "Saturn")
        self.assertEqual(session.calls[1]["titles"], "Saturn")

    def test_preserves_a_match_that_already_worked(self):
        """Scoring must not cost us the matches the cascade already got right."""
        apod = self.make_apod(
            "Witness XZ Andromedae Wink", "XZ Andromedae is an eclipsing binary."
        )
        provider, _session = self.provider(
            responses=[
                FakeResponse(search_response("XZ Andromedae", "Nu Andromedae")),
                FakeResponse(WIKIPEDIA_EXTRACT_RESPONSE),
            ]
        )
        result = provider.fetch(apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "XZ Andromedae")
        self.assertIn("eclipsing binary", result.extract)

    def test_cascade_advances_when_a_tier_scores_too_low(self):
        """Tier 1 returns a novelist; the OR tier finds the actual comet."""
        apod = self.make_apod(
            "Comet NEOWISE over Lebanon", "Comet NEOWISE hangs above the cedars."
        )
        provider, session = self.provider(
            responses=[
                FakeResponse(search_response("Yara Zgheib")),
                FakeResponse(search_response("Comet NEOWISE", "C/2016 U1 (NEOWISE)")),
                FakeResponse(
                    extract_response("Comet NEOWISE", "C/2020 F3 (NEOWISE) is a comet.")
                ),
            ]
        )
        result = provider.fetch(apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "Comet NEOWISE")
        self.assertEqual(session.calls[0]["srsearch"], "Comet NEOWISE over Lebanon")
        self.assertEqual(
            session.calls[1]["srsearch"], "Comet OR NEOWISE OR over OR Lebanon"
        )

    def test_a_weak_tier_one_hit_does_not_stop_the_cascade(self):
        """The old behaviour: any hit at all ended the search."""
        apod = self.make_apod("Ice Halos over Bavaria", "Ice crystals split sunlight.")
        provider, session = self.provider(
            responses=[
                FakeResponse(search_response(*BAD_MATCH_CANDIDATES["Ice Halos over Bavaria"])),
                FakeResponse(search_response("Halo (optical phenomenon)")),
                FakeResponse(
                    extract_response("Halo (optical phenomenon)", "A halo is an optical phenomenon.")
                ),
            ]
        )
        result = provider.fetch(apod)

        self.assertEqual(result.status, SupplementalInfo.Status.FOUND)
        self.assertEqual(result.matched_title, "Halo (optical phenomenon)")
        self.assertEqual(len(session.calls), 3)
