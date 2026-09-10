#!/bin/sh
# Applies migrations before handing off to the CMD, so `docker compose up`
# yields a working application with no manual migration step.
set -e

echo "Applying database migrations..."

# docker-compose waits on the db healthcheck, but a standalone `docker run`
# against an external database has no such guarantee -- so retry briefly.
attempt=1
max_attempts=10
until python manage.py migrate --noinput; do
    if [ "$attempt" -ge "$max_attempts" ]; then
        echo "Database still unreachable after $max_attempts attempts; giving up." >&2
        exit 1
    fi
    echo "Migration attempt $attempt failed; retrying in 3s..." >&2
    attempt=$((attempt + 1))
    sleep 3
done

echo "Migrations applied. Starting: $*"
exec "$@"
