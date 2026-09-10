"""Scoring Wikipedia search candidates against an APOD entry.

Search alone is not enough. MediaWiki's relevance ranking returns *something*
for almost any query, and for a title like "Pink Aurora over Crater Lake" that
something is "Mono Lake" -- plausible, confidently wrong, and indistinguishable
from a good match unless the candidates are actually compared. This module does
the comparing.

Deliberately free of Django imports: pure functions over strings, so they can be
tuned and tested in isolation.
"""

import re

# The list is short on purpose. These are the words that carry no subject
# information in an APOD title -- "Pink Aurora *over* Crater Lake".
STOPWORDS = frozenset(
    {"the", "a", "an", "of", "over", "from", "at", "in", "on", "and", "to"}
)

# How much of the explanation counts as context. The opening sentences name the
# subject; further in, APOD explanations wander into related topics that produce
# false matches.
EXPLANATION_CHARS = 500

# A candidate word found in the APOD title is strong evidence. The same word
# found only in the explanation is weak evidence -- an explanation of ice halos
# mentions "rainbow" in passing, which is exactly how the page *Rainbow* was
# being returned for "Ice Halos over Bavaria".
EXPLANATION_WEIGHT = 0.5

# Guards the substring rule below against noise from short fragments.
MIN_SUBSTRING_LENGTH = 4

# Tuned against real APOD titles and live MediaWiki results; see README.
MATCH_THRESHOLD = 0.6

# Wikipedia's parenthetical qualifier is metadata, not part of the subject's
# name: "Halo (optical phenomenon)" is the page for "halo".
_DISAMBIGUATOR = re.compile(r"\s*\([^)]*\)")
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text):
    """Lowercase `text` into meaningful word tokens.

    Apostrophes are removed rather than split on, so "Cat's" and "Cats" agree.
    """
    if not text:
        return []
    lowered = text.lower().replace("'", "").replace("’", "")
    return [token for token in _WORD.findall(lowered) if token not in STOPWORDS]


def strip_disambiguator(title):
    """Drop a trailing parenthetical qualifier from a Wikipedia page title."""
    return _DISAMBIGUATOR.sub("", title or "").strip()


def score_candidate(candidate_title, apod_title, explanation=""):
    """Score a Wikipedia page title against an APOD entry, from 0.0 to 1.0.

    Every meaningful word in the candidate's title must be accounted for by the
    APOD entry. Normalizing by the candidate's length is what rejects
    "Night Warriors: Darkstalkers' Revenge" for "Saturn at Night": one of its
    four words matches, so it scores 0.25.
    """
    return _score(candidate_title, apod_title, explanation)[0]


def _score(candidate_title, apod_title, explanation=""):
    """Return `(score, matched weight)` for one candidate.

    The unnormalized weight is kept alongside the score because normalizing by
    candidate length makes a short generic title score as well as a specific
    one -- *Nebula* and *Cat's Eye Nebula* both score 1.0 against "The Cat's Eye
    Nebula from Hubble". `best_match` uses the weight to break that tie toward
    the more specific page.
    """
    candidate_tokens = tokenize(strip_disambiguator(candidate_title))
    if not candidate_tokens:
        return 0.0, 0.0

    title_tokens = set(tokenize(apod_title))
    explanation_tokens = set(tokenize((explanation or "")[:EXPLANATION_CHARS]))

    total = 0.0
    for token in candidate_tokens:
        if token in title_tokens or _matches_by_substring(token, title_tokens):
            total += 1.0
        elif token in explanation_tokens:
            total += EXPLANATION_WEIGHT

    return total / len(candidate_tokens), total


def _matches_by_substring(token, title_tokens):
    """Bridge compound words the tokenizer splits differently.

    APOD writes "Fishhead"; Wikipedia titles the page "Fish Head Nebula". Both
    directions are checked, and only for tokens long enough that containment
    means something.
    """
    if len(token) < MIN_SUBSTRING_LENGTH:
        return False
    return any(
        token in title_token or title_token in token
        for title_token in title_tokens
        if len(title_token) >= MIN_SUBSTRING_LENGTH
    )


def best_match(candidate_titles, apod_title, explanation=""):
    """Return the highest-scoring candidate as `(title, score)`.

    Equal scores are broken toward the candidate that accounts for more of the
    APOD entry, and only then by MediaWiki's own ranking. Returns `(None, 0.0)`
    for an empty candidate list.
    """
    best_title, best_key = None, (0.0, 0.0)
    for candidate in candidate_titles:
        key = _score(candidate, apod_title, explanation)
        if key > best_key:
            best_title, best_key = candidate, key

    if best_title is None and candidate_titles:
        # Every candidate scored 0.0; still report one so the miss is diagnosable.
        return candidate_titles[0], 0.0
    return best_title, best_key[0]
