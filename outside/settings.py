"""
Django settings for the Outside project.

Configuration is read from the environment via django-environ. Secrets have no
defaults on purpose: a missing NASA_API_KEY or SECRET_KEY raises at startup
rather than silently degrading (e.g. falling back to NASA's DEMO_KEY).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]),
    NASA_API_TIMEOUT=(float, 10.0),
    WIKIPEDIA_API_TIMEOUT=(float, 5.0),
    SUPPLEMENTAL_ENABLED=(bool, True),
)

# Read .env when present. In Docker the values arrive as real environment
# variables, so this is a convenience for other run styles rather than a
# requirement.
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)


# --- Core ------------------------------------------------------------------

# No default: an unset SECRET_KEY must fail loudly.
SECRET_KEY = env("SECRET_KEY")

DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

ROOT_URLCONF = "outside.urls"

WSGI_APPLICATION = "outside.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Applications ----------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apod",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the Browsable API's CSS/JS under gunicorn with DEBUG=False.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --- Database --------------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL")}


# --- Password validation ---------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization --------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --- Static files ----------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


# --- Django REST Framework -------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        # Left enabled deliberately: gives reviewers a formatted view in a browser.
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}


# --- APOD application ------------------------------------------------------

# No default: falling back to DEMO_KEY would hide a misconfiguration behind a
# severely rate-limited key.
NASA_API_KEY = env("NASA_API_KEY")
NASA_API_URL = env("NASA_API_URL", default="https://api.nasa.gov/planetary/apod")
NASA_API_TIMEOUT = env("NASA_API_TIMEOUT")

WIKIPEDIA_API_URL = env(
    "WIKIPEDIA_API_URL", default="https://en.wikipedia.org/w/api.php"
)
WIKIPEDIA_API_TIMEOUT = env("WIKIPEDIA_API_TIMEOUT")

# Escape hatch for demos/offline work; supplemental lookups are best-effort
# either way and never affect whether the endpoint succeeds.
SUPPLEMENTAL_ENABLED = env("SUPPLEMENTAL_ENABLED")


# --- Logging ---------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apod": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
