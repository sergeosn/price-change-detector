import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError

from api.main import create_api

# Endpoints run in worker threads, so test data must be committed to be visible there.
pytestmark = pytest.mark.django_db(transaction=True)


def test_health_does_not_require_api_key(anon_client):
    response = anon_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_database_failure(anon_client, monkeypatch):
    def broken_database():
        raise OperationalError("database is locked")

    monkeypatch.setattr("api.routers.health.ping_database", broken_database)
    response = anon_client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_openapi_docs_are_served(anon_client):
    assert anon_client.get("/api/docs").status_code == 200
    schema = anon_client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "Price Change Detector API"


def test_create_api_requires_api_key(settings):
    settings.API_KEY = ""
    with pytest.raises(ImproperlyConfigured, match="API_KEY"):
        create_api()
