"""ASGI entry point: FastAPI serves /api, Django (admin) is mounted under /admin.

Run: uvicorn config.asgi:app (from the src directory, or with --app-dir src).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Sets Django up; must happen before anything that imports models.
django_app = get_asgi_application()

from django.conf import settings  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

from api.main import create_api  # noqa: E402

app = create_api()
app.mount("/admin", django_app)
app.mount("/static", StaticFiles(directory=settings.STATIC_ROOT, check_dir=False), name="static")
