"""Django settings. Every value comes from environment variables (see .env.example)."""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

SRC_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SRC_DIR.parent


def env_str(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, "")
    if value == "":
        if default is None:
            raise ImproperlyConfigured(f"Environment variable {name} is required")
        return default
    return value


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    return int(env_str(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(env_str(name, str(default)))


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in env_str(name, default).split(",") if item.strip()]


SECRET_KEY = env_str("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

DATABASES = {
    "default": dj_database_url.parse(
        env_str("DATABASE_URL", f"sqlite:///{PROJECT_DIR / 'data' / 'db.sqlite3'}")
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # The API process and the scheduler write to the same file: WAL lets readers work
    # during writes, IMMEDIATE transactions take the write lock up front, and the
    # 5 second timeout is SQLite's busy timeout.
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {
            "init_command": "PRAGMA journal_mode=WAL;",
            "timeout": 5,
            "transaction_mode": "IMMEDIATE",
        }
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = PROJECT_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # httpx logs every request URL at INFO, and the Telegram URL contains the bot token.
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}

# --- Application settings ---------------------------------------------------------

API_KEY = os.environ.get("API_KEY", "")
CHECK_INTERVAL_HOURS = env_int("CHECK_INTERVAL_HOURS", 24)
SCHEDULER_TICK_SECONDS = env_int("SCHEDULER_TICK_SECONDS", 60)
REQUEST_DELAY_MIN = env_float("REQUEST_DELAY_MIN", 1.0)
REQUEST_DELAY_MAX = env_float("REQUEST_DELAY_MAX", 3.0)
FETCH_TIMEOUT_SECONDS = env_float("FETCH_TIMEOUT_SECONDS", 15.0)
FETCH_ACCEPT_LANGUAGE = env_str("FETCH_ACCEPT_LANGUAGE", "uk,ru;q=0.9,en;q=0.8")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
