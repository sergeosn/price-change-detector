"""FastAPI application factory."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.deps import db_connection, require_api_key
from api.routers import domain_rules, health, products
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
    if settings.CORS_ALLOWED_ORIGINS:
        # Auth is the X-API-Key header, so no cookies/credentials are needed cross-origin.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ALLOWED_ORIGINS,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["X-API-Key", "Content-Type"],
            allow_credentials=False,
        )
    protected = [Depends(require_api_key), Depends(db_connection)]
    app.include_router(health.router, prefix=API_PREFIX, dependencies=[Depends(db_connection)])
    app.include_router(domain_rules.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(products.router, prefix=API_PREFIX, dependencies=protected)
    app.add_exception_handler(NotFoundError, _not_found_handler)
    app.add_exception_handler(DuplicateError, _duplicate_handler)
    return app


async def _not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _duplicate_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})
