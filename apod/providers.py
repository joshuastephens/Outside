"""Supplemental data providers.

A provider takes an APOD and returns extra context about its subject. The
interface is deliberately narrow -- `fetch(apod) -> SupplementalResult` -- so an
LLM-backed provider could replace the Wikipedia one without the view or the
service layer changing.
"""

import abc
import dataclasses
import logging

import requests
from django.conf import settings

from .models import SupplementalInfo

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SupplementalResult:
    """A provider's answer, including the answer "nothing was found".

    `status` is a `SupplementalInfo.Status` value. A miss or a failure carries a
    `reason` instead of raising, because a failed enrichment must never take the
    endpoint down with it.
    """

    source: str
    status: str
    matched_title: str | None = None
    url: str | None = None
    extract: str = ""
    reason: str = ""
    raw_response: dict = dataclasses.field(default_factory=dict)

    @classmethod
    def not_found(cls, source, reason, raw_response=None):
        return cls(
            source=source,
            status=SupplementalInfo.Status.NOT_FOUND,
            reason=reason,
            raw_response=raw_response or {},
        )

    @classmethod
    def error(cls, source, reason):
        return cls(
            source=source, status=SupplementalInfo.Status.ERROR, reason=reason
        )


class SupplementalProvider(abc.ABC):
    """Base class for supplemental sources."""

    source = "unknown"

    @abc.abstractmethod
    def fetch(self, apod):
        """Return a `SupplementalResult` for `apod`. Must not raise."""


class WikipediaProvider(SupplementalProvider):
    """Looks up an APOD's subject on Wikipedia via the MediaWiki API.

    APOD titles are editorial rather than literal -- "Witness XZ Andromedae
    Wink" is about the star XZ Andromedae -- so a direct page lookup on the
    title always misses. Searching is the right tool, but MediaWiki ANDs every
    term by default, and that alone still returns nothing for a title like that
    one. So the search runs as a cascade, stopping at the first query that
    returns a hit:

      1. the title verbatim -- correct when it names its subject outright
         ("The Cat's Eye Nebula from Hubble")
      2. the segment before a colon -- APOD's "Subject: editorial phrase" form
         puts the literal subject first ("IC 1795: The Fishhead Nebula")
      3. the terms OR-ed together -- lets relevance ranking find the subject
         inside the prose, which is what rescues the XZ Andromedae case

    The top hit is then fetched for its intro extract. Steps run only when the
    previous one came up empty, and only on a cache miss, so the common case is
    still two round trips.
    """

    source = "wikipedia"

    def __init__(self, api_url=None, timeout=None, session=None):
        self.api_url = api_url or settings.WIKIPEDIA_API_URL
        self.timeout = (
            timeout if timeout is not None else settings.WIKIPEDIA_API_TIMEOUT
        )
        self.session = session or requests

    def fetch(self, apod):
        try:
            return self._fetch(apod)
        except requests.RequestException as exc:
            logger.warning("Wikipedia lookup failed for %s: %s", apod.date, exc)
            return SupplementalResult.error(self.source, f"Request failed: {exc}")
        except ValueError as exc:
            logger.warning("Wikipedia returned unusable JSON for %s: %s", apod.date, exc)
            return SupplementalResult.error(self.source, f"Malformed response: {exc}")

    def _fetch(self, apod):
        title = (apod.title or "").strip()
        if not title:
            return SupplementalResult.not_found(
                self.source, "APOD has no title to search on."
            )

        search, hits = self._search(title)
        if not hits:
            return SupplementalResult.not_found(
                self.source,
                f"No Wikipedia search results for {title!r}.",
                raw_response=search,
            )

        matched_title = hits[0].get("title")
        if not matched_title:
            return SupplementalResult.not_found(
                self.source,
                "Wikipedia search result had no title.",
                raw_response=search,
            )

        detail = self._get(
            {
                "action": "query",
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "redirects": 1,
                "titles": matched_title,
                "format": "json",
            }
        )
        pages = detail.get("query", {}).get("pages", {})
        # Keyed by page id; a value of "-1" means the page does not exist.
        page = next((p for p in pages.values() if str(p.get("pageid", "-1")) != "-1"), None)
        if page is None:
            return SupplementalResult.not_found(
                self.source,
                f"Wikipedia page {matched_title!r} could not be retrieved.",
                raw_response=detail,
            )

        extract = (page.get("extract") or "").strip()
        if not extract:
            return SupplementalResult.not_found(
                self.source,
                f"Wikipedia page {matched_title!r} has no intro extract.",
                raw_response=detail,
            )

        return SupplementalResult(
            source=self.source,
            status=SupplementalInfo.Status.FOUND,
            matched_title=page.get("title", matched_title),
            url=page.get("fullurl"),
            extract=extract,
            raw_response=detail,
        )

    def _search(self, title):
        """Run the query cascade, returning (last response, hits)."""
        response = {}
        for query in self._candidate_queries(title):
            response = self._get(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": 1,
                    "format": "json",
                }
            )
            hits = response.get("query", {}).get("search", [])
            if hits:
                logger.info("Wikipedia matched %r via query %r", title, query)
                return response, hits
        return response, []

    @staticmethod
    def _candidate_queries(title):
        """Successively looser queries for one editorial title.

        Deduplicated, because a title without a colon or with a single term
        collapses these into the same string.
        """
        candidates = [title]
        if ":" in title:
            candidates.append(title.split(":", 1)[0].strip())
        terms = [term for term in title.replace(":", " ").split() if term]
        if len(terms) > 1:
            candidates.append(" OR ".join(terms))

        seen = set()
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                yield candidate

    def _get(self, params):
        response = self.session.get(
            self.api_url,
            params=params,
            timeout=self.timeout,
            headers={"User-Agent": "Outside/1.0 (APOD coding challenge)"},
        )
        response.raise_for_status()
        return response.json()


def get_default_provider():
    """The provider the service layer uses. Swap here to change sources."""
    return WikipediaProvider()
