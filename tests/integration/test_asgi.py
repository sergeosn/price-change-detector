import pytest
from fastapi.testclient import TestClient

from config.asgi import app

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_admin_is_mounted_under_admin_prefix(client):
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/login/?next=/admin/"


def test_admin_login_page_uses_prefixed_urls(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
    assert 'action="/admin/login/"' in response.text
    assert "/static/admin/css/base.css" in response.text


def test_api_is_served_by_the_same_app(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
