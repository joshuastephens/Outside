# python:3.12-slim: Debian-based, so binary wheels (psycopg[binary]) install
# cleanly -- Alpine's musl would force source builds, and a full Ubuntu base is
# unnecessary bulk.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so application edits do not invalidate this layer.
COPY requirements.txt ./
RUN pip install --requirement requirements.txt

COPY . .

# Collect the Browsable API's assets for whitenoise. Placeholder values satisfy
# settings' required-secret checks; nothing here is baked into the image, and
# collectstatic never touches the database.
RUN SECRET_KEY=build-time-only \
    NASA_API_KEY=build-time-only \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    python manage.py collectstatic --noinput

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

# The challenge specifies 8080, not Django's default 8000.
EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "outside.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]
