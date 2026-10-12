"""FastAPI dependencies: API key, DB connection hygiene, pagination, services."""

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from django.conf import settings
from django.db import close_old_connections
from fastapi import Depends, HTTPException, Query, Security, status
from fastapi.security import APIKeyHeader

from notifications.base import Notifier
from notifications.factory import get_notifier
from tracker.services.fetcher import PageFetcher, get_fetcher

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: Annotated[str | None, Security(api_key_header)]) -> None:
    if not api_key or not secrets.compare_digest(api_key.encode(), settings.API_KEY.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key"
        )


def db_connection() -> Iterator[None]:
    """Do what Django does around every request: drop stale/broken DB connections."""
    close_old_connections()
    try:
        yield
    finally:
        close_old_connections()


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


def get_page_fetcher() -> PageFetcher:
    return get_fetcher()


def get_price_notifier() -> Notifier:
    return get_notifier()


PaginationDep = Annotated[Pagination, Depends(pagination)]
FetcherDep = Annotated[PageFetcher, Depends(get_page_fetcher)]
NotifierDep = Annotated[Notifier, Depends(get_price_notifier)]
