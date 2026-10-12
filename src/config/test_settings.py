"""Settings for the test suite: fixed secrets, no delays, notifications off."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ["DATABASE_URL"] = "sqlite://:memory:"

from config.settings import *  # noqa: E402, F403

API_KEY = "test-api-key"
REQUEST_DELAY_MIN = 0.0
REQUEST_DELAY_MAX = 0.0
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
