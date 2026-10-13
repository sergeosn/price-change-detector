import pytest
from fastapi.testclient import TestClient

from api.main import create_api

pytestmark = pytest.mark.django_db(transaction=True)

FRONTEND = "http://localhost:5173"
PRODUCTS = "/api/v1/products"


def preflight(client: TestClient, origin: str):
    return client.options(
        PRODUCTS,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key, content-type",
        },
    )


@pytest.fixture
def cors_client(settings) -> TestClient:
    settings.CORS_ALLOWED_ORIGINS = [FRONTEND, "http://localhost:4173"]
    return TestClient(create_api())


def test_preflight_from_allowed_origin_is_accepted(cors_client):
    response = preflight(cors_client, FRONTEND)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-api-key" in allowed_headers
    assert "content-type" in allowed_headers
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_from_other_origin_is_rejected(cors_client):
    response = preflight(cors_client, "https://evil.example")
    assert "access-control-allow-origin" not in response.headers


def test_actual_request_from_allowed_origin_gets_cors_header(cors_client):
    response = cors_client.get(
        PRODUCTS, headers={"Origin": "http://localhost:4173", "X-API-Key": "test-api-key"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4173"


def test_cors_is_disabled_by_default(settings):
    settings.CORS_ALLOWED_ORIGINS = []
    response = preflight(TestClient(create_api()), FRONTEND)
    assert "access-control-allow-origin" not in response.headers
