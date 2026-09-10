# CLAUDE.md

## Project

`Outside` — a Django REST Framework application that fetches NASA's Astronomy
Picture of the Day (APOD), enriches it with supplemental data from an external
source, persists both to Postgres, and exposes them through a single JSON API
endpoint.

## Stack

- Python 3.12
- Django 5.x + Django REST Framework
- PostgreSQL 16 (via `psycopg[binary]` v3 — not psycopg2)
- Docker + docker-compose
- gunicorn (production server, binds port 8080)
- whitenoise (static file serving — required for DRF's Browsable API assets to
  render under gunicorn with `DEBUG=False`)
- Tests: Django's `unittest`-based `TestCase`

Pin all dependency versions in `requirements.txt`.

## Project layout

Create the project with `django-admin startproject outside .` — the trailing
dot matters, as it avoids Django adding a redundant wrapper directory inside
the existing repository folder. The resulting structure:

```
manage.py
outside/          # project package: settings, root URLs, wsgi
apod/             # application: models, views, serializers, clients, tests
```

All application code belongs in the `apod` app, not in the `outside` project
package, which holds configuration only. The WSGI entry point is
`outside.wsgi:application`.

## Architecture decisions

### DB-first retrieval
The endpoint accepts an optional `date` query param (`YYYY-MM-DD`, defaults to
today). Flow:

1. Look up the date in the database
2. On hit — serve from DB, do **not** call the NASA API
3. On miss — call NASA, persist the result, then serve it

Both paths return through the same serializer.

### Models
- `APOD` — one row per date. `date` is `unique=True` (this is the cache key).
  Normalized columns for `title`, `explanation`, `media_type`, `url`, plus a
  `raw_response` JSONField holding the complete unmodified NASA payload.
  NASA omits `copyright` and `hdurl` on some days — do not assume they exist.
- `SupplementalInfo` — FK to `APOD`. Stores source name, matched page title,
  URL, extract text, and the raw provider response. Modeled as a separate table
  so multiple sources per APOD are possible.

### Supplemental data
Wikipedia via the MediaWiki API. APOD titles are editorial rather than literal
(e.g. "Witness XZ Andromedae Wink" refers to the star XZ Andromedae), so:

1. Use the search endpoint (`action=query&list=search`) with the APOD title —
   the search index tolerates surrounding prose
2. Fetch the intro extract of the top result
   (`prop=extracts&exintro&explaintext`)
3. If nothing useful is found, persist a null result with a reason rather than
   failing

Implement behind a small provider interface (e.g. `SupplementalProvider.fetch()`)
so an LLM-backed provider could be substituted without touching the view.

**Supplemental lookup failures must never break the endpoint.** If Wikipedia is
unreachable or returns nothing, still persist and return the NASA data.

### Secrets
`NASA_API_KEY` is read from the environment via `django-environ`.

- `.env` is gitignored
- `.env.example` is committed with placeholder values
- Settings must raise on a missing key — never silently fall back to `DEMO_KEY`

### Docker
Two services:

- `web` — built from `python:3.12-slim`. Not Ubuntu (bloat), not Alpine (musl
  breaks binary wheels). Runs
  `gunicorn outside.wsgi:application --bind 0.0.0.0:8080`.
- `db` — official `postgres:16-alpine` image, with a healthcheck. `web` must
  use `depends_on: condition: service_healthy` or it will race the database on
  startup.

An entrypoint script runs `python manage.py migrate` before starting gunicorn,
so that `docker compose up` produces a working application with no manual
migration step.

The Dockerfile must work standalone and listen on **8080**, not Django's
default 8000 — this is an explicit challenge requirement. docker-compose is
supplementary.

## Conventions

- **Do not use ViewSets or routers.** This is one read-only endpoint; a single
  `APIView` (or `@api_view` function) is the correct altitude.
- Wrap external API calls in a client class/module rather than calling
  `requests` inline in views — this also makes mocking clean in tests.
- Handle these edge cases explicitly, with clear 4xx responses rather than
  500s: malformed date strings, dates before 1995-06-16, future dates. The
  NASA API returns 400 for the latter two.
- Tests must mock all external HTTP. No test may hit the real NASA or
  Wikipedia APIs.

## Optional frontend

DRF's Browsable API is enabled by default and should be left on — it gives
reviewers a formatted view of the endpoint in a browser.

Time permitting, a minimal page may be added: a date picker that displays the
returned photo or video. Constraints if built:

- Server-rendered with a Django template at `/`, with the API remaining at
  `/api/apod/`. A plain `<form method="get">` with `<input type="date">`. No
  JavaScript, no frontend framework, no build step.
- The page view must call the same service function as the API view. It must
  not make an HTTP request to the application's own endpoint.
- `media_type: "video"` is ambiguous in APOD data — the `url` may be a direct
  video file or a YouTube/Vimeo embed URL. Handle both (`<video>` vs
  `<iframe>`).

## Deliverables

- `README.md` — setup and execution steps, documented assumptions, and a
  "Post-Challenge Notes" section covering what would be done with more time
- `PROMPT.md` — complete prompt history from the build session
