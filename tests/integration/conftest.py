"""API test fixtures: the FastAPI app with fake fetcher/notifier and HTTP clients."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_page_fetcher, get_price_notifier
from api.main import create_api
from tests.helpers import FakeFetcher, FakeNotifier

API_KEY = "test-api-key"


@pytest.fixture
def fake_fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def fake_notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture
def api_app(fake_fetcher, fake_notifier) -> FastAPI:
    app = create_api()
    app.dependency_overrides[get_page_fetcher] = lambda: fake_fetcher
    app.dependency_overrides[get_price_notifier] = lambda: fake_notifier
    return app


@pytest.fixture
def api_client(api_app) -> TestClient:
    return TestClient(api_app, headers={"X-API-Key": API_KEY})


@pytest.fixture
def anon_client(api_app) -> TestClient:
    return TestClient(api_app)
