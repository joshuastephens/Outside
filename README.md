# Outside

A Django REST Framework service that fetches NASA's [Astronomy Picture of the
Day](https://api.nasa.gov/) (APOD), enriches it with supplemental context from
Wikipedia, persists both to PostgreSQL, and serves them through a single
read-only JSON endpoint.

The database is the cache: a date that has been requested before is served
straight from Postgres and never touches NASA again.

---

## Quick start

Requires Docker. Nothing else — no local Python, no local Postgres.

```bash
cp .env.example .env
```

Then edit `.env` and set two values:

| Variable | How to get it |
| --- | --- |
| `NASA_API_KEY` | Free key from <https://api.nasa.gov/> |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |

No local Python? `docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(64))"` does the same job.

`SECRET_KEY` signs sessions, CSRF tokens, and cookies. Neither variable has a
fallback: a missing value raises at startup rather than booting into a broken
state. Django's own `SECRET_KEY` guard is lazy — an empty key passes
`manage.py check` and only fails on the first request — so the check is made
eager here.

Then:

```bash
docker compose up --build
```

The application is at <http://localhost:8080/api/apod/>. Migrations run
automatically on startup — there is no manual migration step.

### Try it

```bash
curl "http://localhost:8080/api/apod/?date=2024-05-01"
```

Or open <http://localhost:8080/api/apod/> in a browser for DRF's Browsable API,
which renders the same response with a formatted, clickable interface.

---

## API

### `GET /api/apod/`

| Query param | Type | Default | Notes |
| --- | --- | --- | --- |
| `date` | `YYYY-MM-DD` | today | Must be between 1995-06-16 and today, inclusive |

NASA's API also accepts `start_date`/`end_date`, `count`, and `thumbs`. This
service exposes one date at a time, so only `date` is supported.

#### Response

```json
{
  "date": "2026-09-09",
  "title": "Witness XZ Andromedae Wink",
  "explanation": "Is this star winking at us? ...",
  "media_type": "video",
  "url": "https://apod.nasa.gov/apod/image/2609/xz_and.mp4",
  "hdurl": null,
  "copyright": null,
  "raw_response": {
    "date": "2026-09-09",
    "explanation": "Is this star winking at us? ...",
    "media_type": "video",
    "service_version": "v1",
    "title": "Witness XZ Andromedae Wink",
    "url": "https://apod.nasa.gov/apod/image/2609/xz_and.mp4"
  },
  "supplemental": [
    {
      "source": "wikipedia",
      "status": "found",
      "matched_title": "XZ Andromedae",
      "url": "https://en.wikipedia.org/wiki/XZ_Andromedae",
      "extract": "XZ Andromedae (also known as XZ And) is a binary star in the constellation Andromeda...",
      "reason": ""
    }
  ]
}
```

The top-level fields are the stable contract. `raw_response` carries NASA's
complete, unmodified payload alongside them, so nothing NASA sends is lost even
if it has no column of its own.

`supplemental[].status` is one of `found`, `not_found`, or `error`. On anything
but `found`, `reason` explains what happened and the other fields are null or
empty — a failed lookup is recorded, not hidden, and never affects the NASA data
in the same response.

#### Status codes

| Code | When |
| --- | --- |
| `200` | Success, from the database or freshly fetched |
| `400` | Malformed date, a date before 1995-06-16, or a future date |
| `404` | A valid date NASA has no entry for |
| `502` | NASA unreachable, timed out, rate-limited, or unusable response |

Every error returns `{"detail": "..."}` with a specific message:

```bash
$ curl "http://localhost:8080/api/apod/?date=05/01/2024"
{"detail":"Could not parse date '05/01/2024'. Expected format YYYY-MM-DD."}

$ curl "http://localhost:8080/api/apod/?date=1995-06-15"
{"detail":"1995-06-15 is before the first Astronomy Picture of the Day (1995-06-16)."}
```

Out-of-range dates are rejected before any upstream call is made.

---

## Running the tests

```bash
docker compose up -d db
docker compose run --rm --entrypoint python web manage.py test
```

68 tests, all external HTTP mocked. `NoNetworkTestCase` patches
`requests.Session.request` to raise, so a test that forgets to mock something
fails loudly rather than quietly hitting the real NASA or Wikipedia APIs.

Coverage:

| Area | File |
| --- | --- |
| Cache hit / miss, date defaulting, validation, graceful degradation | `apod/tests/test_api.py` |
| Response shape | `apod/tests/test_serializers.py` |
| Every NASA response shape → its mapped exception | `apod/tests/test_clients.py` |
| Search cascade, candidate scoring, and every way a lookup comes up empty | `apod/tests/test_providers.py` |
| Tokenizing, scoring, and threshold behaviour in isolation | `apod/tests/test_matching.py` |

The scoring tests use the candidate lists live MediaWiki actually returns for
real APOD titles, so they pin the exact behaviour described above rather than
invented examples.

**The run is silent by design.** Several tests deliberately drive failure paths
— a provider that raises, a NASA timeout, a malformed date — and the production
code logs each one, correctly and with a full traceback. `QuietLogsMixin` in
`apod/tests/base.py` captures those records for the duration of a test instead
of printing them, so a passing run does not look like a broken one. Nothing is
discarded: the tests that provoke a failure assert with `assertLogs` that it was
logged, at the right level, with the traceback attached. The project's logging
configuration is untouched and behaves normally in production.

---

## Running without docker-compose

The Dockerfile stands alone and listens on 8080. With a Postgres reachable from
the container:

```bash
docker build -t outside .
docker run --rm -p 8080:8080 \
  -e SECRET_KEY=... \
  -e NASA_API_KEY=... \
  -e DATABASE_URL=postgres://user:pass@host:5432/dbname \
  outside
```

The entrypoint retries migrations for up to 30 seconds, so the container
tolerates a database that is still coming up.

---

## Architecture

```
apod/
  models.py       APOD, SupplementalInfo
  clients.py      NasaAPODClient  -- all NASA HTTP
  providers.py    SupplementalProvider interface + WikipediaProvider
  matching.py     candidate scoring -- pure functions, no Django
  services.py     get_apod_for_date() -- the DB-first flow
  serializers.py  response shape
  views.py        one APIView
outside/          settings, root URLs, WSGI
```

**DB-first retrieval.** `get_apod_for_date()` checks Postgres first. A hit is
returned without contacting NASA at all. A miss fetches, persists, enriches,
and returns. Both paths exit through the same serializer, so the response is
byte-identical either way.

**One `APIView`, no ViewSet or router.** There is a single read-only resource
here. Routing machinery would be more scaffolding than the resource needs.

**A service layer, not just a view.** `get_apod_for_date()` exists separately so
that a second presentation layer — the optional server-rendered date-picker page
— can call the same function directly rather than making an HTTP request back
into this application.

**Two tables, not one.** `SupplementalInfo` is a separate table with an FK to
`APOD` so several providers can enrich the same entry. `WikipediaProvider`
implements a narrow `SupplementalProvider.fetch(apod) -> SupplementalResult`
interface; an LLM-backed provider could replace it without the view or the
service layer changing.

**External calls behind client classes.** No `requests` call appears in a view.
This keeps transport concerns in one place and gives tests a single seam to mock.

### Finding the right Wikipedia page

APOD titles are editorial rather than literal, so a direct page lookup on the
title misses. Searching is the right tool — but it has two distinct failure
modes, and they need different fixes.

#### Problem 1: no hits at all

MediaWiki ANDs every search term, so a full editorial title matches nothing.
Verified against the live API:

```
"Witness XZ Andromedae Wink"     -> 0 hits
"IC 1795: The Fishhead Nebula"   -> 0 hits
```

So the search runs as a **cascade** of progressively looser queries:

1. **The title verbatim** — correct when it names its subject outright
   ("The Cat's Eye Nebula from Hubble" → *Cat's Eye Nebula*)
2. **The segment before a colon** — APOD's "Subject: editorial phrase" form puts
   the literal subject first ("IC 1795: The Fishhead Nebula" → *Fish Head Nebula*)
3. **The terms OR-ed together** — lets relevance ranking find the subject inside
   the prose ("Witness XZ Andromedae Wink" → *XZ Andromedae*)

#### Problem 2: plausible wrong hits

The cascade solves "no hits" — and thereby exposes the worse failure. MediaWiki
returns *something* for almost any query, so tier 1 nearly always fires, and
whatever relevance ranking hands back gets accepted unconditionally. Across a
sample of 16 real APOD titles, a match was returned every single time and five
were confidently wrong:

| APOD title | Accepted page |
| --- | --- |
| Pink Aurora over Crater Lake | *Mono Lake* |
| Comet NEOWISE over Lebanon | *Yara Zgheib* (a novelist) |
| Colorful Clouds Over Sicily | *Equestrian Portrait of Joachim Murat* |
| Ice Halos over Bavaria | *Rainbow* (a different phenomenon) |
| Saturn at Night | *Night Warriors: Darkstalkers' Revenge* |

Titles naming an astronomical object worked well; titles about places, weather,
and optical phenomena failed, because common words like "Night" and "Lake"
dominate the ranking. A wrong extract presented as fact is worse than no
extract, so the fix is to stop trusting the top hit.

#### Scoring

Each tier now requests **five** candidates and scores them (`apod/matching.py`):

- Both the candidate title and the APOD context — its title plus the first 500
  characters of its explanation — are lowercased, split into words, and stripped
  of stopwords (`the`, `a`, `an`, `of`, `over`, `from`, `at`, `in`, `on`, `and`,
  `to`).
- Each word of the **candidate** scores `1.0` if it appears in the APOD title,
  or `0.5` if it appears only in the explanation.
- The total is divided by the number of words in the candidate title.

Normalizing by candidate length is what does the rejecting: *Night Warriors:
Darkstalkers' Revenge* matches one of its four words against "Saturn at Night",
so it scores **0.25**. *Mono Lake* matches one of two against "Pink Aurora over
Crater Lake" — **0.50**. Meanwhile *XZ Andromedae* and *Cat's Eye Nebula* both
score **1.00**. The threshold sits at **0.60**, inside that gap.

Three details earn their keep:

- **Explanation matches are weighted at 0.5** — below the threshold by
  construction, so a word mentioned in passing can never carry a match on its
  own. An explanation of ice halos mentions rainbows; that is precisely how
  *Rainbow* was being accepted.
- **Parenthetical qualifiers are stripped.** *Halo (optical phenomenon)* is
  scored as "Halo", the subject it actually names.
- **Substring matching bridges compound words** (4+ characters). APOD writes
  "Fishhead"; Wikipedia titles the page *Fish Head Nebula*.

A tier is accepted only if its best candidate clears the threshold; otherwise
the cascade advances. That combination is what rescues "Comet NEOWISE over
Lebanon" — tier 1 offers only the novelist at 0.00, so tier 3 runs and finds
*Comet NEOWISE* at 1.00. When nothing anywhere clears the bar, the result is a
recorded `not_found` naming the closest candidate and its score:

```json
{
  "source": "wikipedia",
  "status": "not_found",
  "reason": "No Wikipedia result scored above 0.60 for 'Pink Aurora over Crater Lake'; best candidate was 'Mono Lake' at 0.50."
}
```

#### Verified against the live API

All five bad matches are rejected and all eight good ones preserved. Three of
the five turn into *correct* matches rather than misses, because the cascade now
advances past a weak tier:

| APOD title | Was | Now |
| --- | --- | --- |
| Pink Aurora over Crater Lake | *Mono Lake* | `not_found` (best 0.50) |
| Colorful Clouds Over Sicily | *Equestrian Portrait…* | `not_found` (best 0.33) |
| Comet NEOWISE over Lebanon | *Yara Zgheib* | *Comet NEOWISE* ✓ |
| Ice Halos over Bavaria | *Rainbow* | *Halo (optical phenomenon)* ✓ |
| Saturn at Night | *Night Warriors…* | *Saturn* ✓ |

A separate sweep of 20 unrelated real APOD dates was also run through the
running service. One of those dates failed at the NASA fetch and so never
reached Wikipedia, leaving 19 matches to judge: 17 good or defensible, 1
recorded miss, and 1 lexically perfect but semantically wrong (see
Post-Challenge Notes).

**Failures are contained.** `WikipediaProvider.fetch()` never raises; the service
layer wraps it in a second guard anyway. If Wikipedia is unreachable or finds
nothing, a row recording the reason is stored and the NASA data is returned
normally. Supplemental data is a bonus, never a dependency.

---

## Assumptions

- **"Today" means today in US Eastern time,** not UTC. APOD is published on
  Eastern time and NASA interprets the `date` param the same way. Anchoring to
  UTC caused a real bug during development: for several hours each evening, UTC
  had already rolled over and a bare `GET /api/apod/` returned 404 for a day
  NASA had not published yet.
- **Requesting a date is enough reason to cache it forever.** APOD entries are
  effectively immutable once published, so there is no expiry. A stored row is
  never re-fetched. See Post-Challenge Notes for what would change this.
- **A recorded miss beats a confident wrong answer.** Wikipedia candidates are
  scored and rejected below a threshold rather than accepted on rank, so
  `status: "not_found"` with a reason is a normal, healthy outcome — not a
  malfunction. Scoring is lexical, not semantic, so it rejects unrelated pages
  but cannot catch a page whose title genuinely matches the APOD's wording.
  `matched_title` and `url` are always returned so a consumer can judge the
  match themselves.
- **`copyright` and `hdurl` are optional.** NASA omits them on many days. Both
  are nullable columns and serialize as `null`, never as empty strings.
- **No authentication, no rate limiting.** Out of scope for a single public
  read-only endpoint.
- **A concurrent double-miss on the same date is harmless.** Persistence uses
  `update_or_create` keyed on the unique `date`, so two simultaneous requests
  for an uncached date cost one redundant NASA call and converge on one row.
- **The Browsable API is left enabled deliberately.** It gives reviewers a
  formatted view in a browser. whitenoise serves its assets so it renders
  correctly under gunicorn with `DEBUG=False`.

---

## Post-Challenge Notes

Things I would do with more time, roughly in the order I would do them.

**A cache-refresh path.** Right now a stored row is never re-fetched. That is
correct for published APOD entries, but it means a row persisted while Wikipedia
was down keeps its `error` supplemental result forever. I would add a
`?refresh=1` parameter, or a background job that retries `status=error` rows
with backoff.

**Retries on the NASA call.** A single timeout currently becomes a 502. A couple
of retries with exponential backoff, on a `requests.Session` with a
`urllib3.Retry` adapter, would absorb most transient failures. The client class
is already the right place for it — nothing else would change.

**Make enrichment asynchronous.** A cache miss currently pays for the Wikipedia
round trips inline: worst case, three searches plus an extract before the
response goes out. Moving enrichment to a task queue (Celery, or `django-q` for
something lighter) would return the NASA data immediately and let supplemental
data appear on the next request. The `SupplementalInfo` table is already modeled
to make this a small change — the rows simply arrive later.

**Semantic Wikipedia matching.** Candidate scoring (above) fixed the confident
wrong answers, but it is lexical, and two limits show up in a live sweep:

- *Date-bearing page titles are under-scored.* "A Total Solar Eclipse over
  Wyoming" is correctly served by *Solar eclipse of August 21, 2017*, but that
  page scores 0.40 — the day and year in its title match nothing — so it is
  recorded as a miss. Feeding the APOD's own date into the scoring context would
  fix this precisely, and would also distinguish that page from *Solar eclipse
  of April 8, 2024*, which lexical scoring alone cannot.
- *A perfect lexical match can still be the wrong subject.* "A Road to the
  Stars" matched the 1957 Soviet film of that name at 1.00. No amount of token
  overlap catches this; it needs meaning.

The next step for both is an LLM-backed provider that reads the explanation and
identifies the subject directly. The `SupplementalProvider` interface exists
precisely so that swap is a one-line change in `get_default_provider()`, and the
scoring threshold gives a ready-made way to A/B the two.

**The optional frontend.** A server-rendered page at `/` with a
`<form method="get">` date picker, rendering `<img>`, `<video>`, or `<iframe>`
depending on `media_type` and whether `url` is a direct file or an embed. The
view would call `get_apod_for_date()` directly. `/` currently redirects to the
Browsable API, and the service layer is already factored for this.

**Operational polish.** A `/healthz` endpoint that checks the database (useful
for a container healthcheck on `web`, which currently has none); structured JSON
logging; and request IDs threaded through the client calls.

**Test additions.** A concurrency test for the double-miss path, and a contract
test that replays recorded NASA payloads from several real days to catch
schema drift.
