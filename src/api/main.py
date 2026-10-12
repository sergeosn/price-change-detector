"""FastAPI application factory."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from api.deps import db_connection, require_api_key
from api.routers import domain_rules, health
from tracker.services.errors import DuplicateError, NotFoundError

API_PREFIX = "/api/v1"


def create_api() -> FastAPI:
    if not settings.API_KEY:
        raise ImproperlyConfigured("API_KEY environment variable is required")

    app = FastAPI(
        title="Price Change Detector API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    protected = [Depends(require_api_key), Depends(db_connection)]
    app.include_router(health.router, prefix=API_PREFIX, dependencies=[Depends(db_connection)])
    app.include_router(domain_rules.router, prefix=API_PREFIX, dependencies=protected)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(DuplicateError, _duplicate_handler)
    return app


async def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _duplicate_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})
