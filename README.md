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

42 tests, all external HTTP mocked. `NoNetworkTestCase` patches
`requests.Session.request` to raise, so a test that forgets to mock something
fails loudly rather than quietly hitting the real NASA or Wikipedia APIs.

Coverage:

| Area | File |
| --- | --- |
| Cache hit / miss, date defaulting, validation, graceful degradation | `apod/tests/test_api.py` |
| Response shape | `apod/tests/test_serializers.py` |
| Every NASA response shape → its mapped exception | `apod/tests/test_clients.py` |
| Wikipedia search cascade and every way it comes up empty | `apod/tests/test_providers.py` |

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

### The Wikipedia search cascade

APOD titles are editorial rather than literal, so a direct page lookup on the
title misses. Searching is the right tool — but MediaWiki ANDs every search
term, and that alone still returns **zero hits** for a title like "Witness XZ
Andromedae Wink". Verified against the live API:

```
"Witness XZ Andromedae Wink"     -> 0 hits
"IC 1795: The Fishhead Nebula"   -> 0 hits
```

So the search runs as a cascade, stopping at the first query that returns a hit:

1. **The title verbatim** — correct when it names its subject outright
   ("The Cat's Eye Nebula from Hubble" → *Cat's Eye Nebula*)
2. **The segment before a colon** — APOD's "Subject: editorial phrase" form puts
   the literal subject first ("IC 1795: The Fishhead Nebula" → *Fish Head Nebula*)
3. **The terms OR-ed together** — lets relevance ranking find the subject inside
   the prose ("Witness XZ Andromedae Wink" → *XZ Andromedae*)

The top hit's intro extract is then fetched with
`prop=extracts&exintro&explaintext`. Steps 2 and 3 run only when the previous one
came up empty, and only on a cache miss, so the common case is still two round
trips.

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
- **The top Wikipedia search hit is the right one.** No disambiguation or
  confidence scoring; the extract is presented as "here is what Wikipedia says
  about the likely subject", with `matched_title` and `url` included so a
  consumer can judge the match themselves.
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

**Better Wikipedia matching.** The cascade is a good heuristic but not a
semantic one. Options, in increasing order of effort: check the extract for
overlap with the APOD explanation before accepting a hit; use
`list=search&srqiprofile=` tuning; or replace the whole provider with an
LLM-backed one that reads the explanation and identifies the subject directly.
The provider interface exists precisely so that swap is a one-line change in
`get_default_provider()`.

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
