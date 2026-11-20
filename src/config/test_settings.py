"""Settings for the test suite: fixed secrets, no delays, notifications off."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
# pytest-django creates and drops its own "test_<name>" database on this server.
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or "postgres://pcd:pcd@localhost:5432/pcd"
)

# Tests use a fake embedder; if one ever reached the real model, it must not be downloaded.
os.environ["HF_HUB_OFFLINE"] = "1"

from config.settings import *  # noqa: E402, F403

API_KEY = "test-api-key"
REQUEST_DELAY_MIN = 0.0
REQUEST_DELAY_MAX = 0.0
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
