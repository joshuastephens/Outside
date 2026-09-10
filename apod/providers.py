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

from .matching import MATCH_THRESHOLD, best_match
from .models import SupplementalInfo

logger = logging.getLogger(__name__)

# Wikimedia's User-Agent policy asks that automated clients identify themselves
# with a contact point; a repository URL satisfies it.
USER_AGENT = "Outside/1.0 (https://github.com/joshuastephens/Outside)"


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

    Widening the search is only half the problem. MediaWiki returns *something*
    for nearly any query, so the failure mode that matters is not "no hits" but
    a plausible wrong hit -- "Pink Aurora over Crater Lake" confidently matching
    *Mono Lake*. So each tier requests five candidates and scores them against
    the APOD entry (see `matching.py`); a tier is only accepted if its best
    candidate clears `MATCH_THRESHOLD`, and otherwise the cascade continues.

    That combination is what rescues "Comet NEOWISE over Lebanon": tier 1
    returns only the novelist *Yara Zgheib*, which scores 0.0, so the cascade
    advances and tier 3 finds *Comet NEOWISE* at 1.0.

    When nothing anywhere clears the bar, the result is a recorded `not_found`
    naming the best candidate and its score. A diagnosable miss is a better
    outcome than a confident wrong answer.

    The accepted page is then fetched for its intro extract. Tiers run only
    while the previous one has come up short, and only on a cache miss, so a
    clean match still costs two round trips.
    """

    # Enough candidates for scoring to have something to choose between,
    # without paying for a long tail that never wins.
    search_limit = 5

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

        matched_title, search, best = self._select_candidate(apod, title)
        if matched_title is None:
            return SupplementalResult.not_found(
                self.source,
                self._miss_reason(title, best),
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

    def _select_candidate(self, apod, title):
        """Walk the cascade, scoring each tier's candidates.

        Returns `(accepted title or None, last search response, (best title,
        best score))`. The best-seen pair is carried across tiers so a miss can
        say how close it got.
        """
        best_title, best_score = None, 0.0
        response = {}

        for query in self._candidate_queries(title):
            response = self._search(query)
            candidates = [
                hit["title"]
                for hit in response.get("query", {}).get("search", [])
                if hit.get("title")
            ]
            if not candidates:
                continue

            candidate, score = best_match(candidates, apod.title, apod.explanation)
            if score > best_score:
                best_title, best_score = candidate, score

            if score >= MATCH_THRESHOLD:
                logger.info(
                    "Wikipedia matched %r to %r (score %.2f) via query %r",
                    title,
                    candidate,
                    score,
                    query,
                )
                return candidate, response, (candidate, score)

            logger.debug(
                "Wikipedia tier %r best candidate %r scored %.2f, below %.2f",
                query,
                candidate,
                score,
                MATCH_THRESHOLD,
            )

        return None, response, (best_title, best_score)

    def _miss_reason(self, title, best):
        """Explain a miss in terms a reader can act on."""
        best_title, best_score = best
        if best_title is None:
            return f"No Wikipedia search results for {title!r}."
        return (
            f"No Wikipedia result scored above {MATCH_THRESHOLD:.2f} for "
            f"{title!r}; best candidate was {best_title!r} at {best_score:.2f}."
        )

    def _search(self, query):
        return self._get(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": self.search_limit,
                "format": "json",
            }
        )

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
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response.json()


def get_default_provider():
    """The provider the service layer uses. Swap here to change sources."""
    return WikipediaProvider()
