from django.db import DatabaseError, connection
from fastapi import APIRouter, HTTPException, status

router = APIRouter(tags=["health"])


def ping_database() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


@router.get("/health")
def health() -> dict[str, str]:
    try:
        ping_database()
    except DatabaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable"
        ) from exc
    return {"status": "ok"}
