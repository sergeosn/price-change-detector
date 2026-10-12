import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from notifications.base import NotificationError
from notifications.telegram import TelegramNotifier
from tests.helpers import make_product
from tracker.models import DomainRule, PriceChange

pytestmark = pytest.mark.django_db

TOKEN = "123456:secret-token"
SEND_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)


def change_for(product, old, new):
    return PriceChange.objects.create(
        product=product,
        old_price=None if old is None else Decimal(old),
        new_price=Decimal(new),
        detected_at=NOW,
    )


@respx.mock
def test_price_drop_below_target_is_highlighted():
    DomainRule.objects.create(domain="shop.example", currency="UAH")
    product = make_product(name="Apple iPhone 15", target_price=Decimal("35000.00"))
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    TelegramNotifier(TOKEN, "42").price_changed(
        product, change_for(product, "37999.00", "34999.00")
    )

    payload = json.loads(route.calls.last.request.content)
    assert payload["chat_id"] == "42"
    assert payload["disable_web_page_preview"] is True
    assert payload["text"] == (
        "🎯 Target price reached!\n"
        "📉 Price dropped\n"
        "Apple iPhone 15\n"
        "37999.00 → 34999.00 UAH (-7.89%)\n"
        "Target price: 35000.00 UAH\n"
        "https://shop.example/item/1"
    )


@respx.mock
def test_price_rise_without_target_or_currency():
    product = make_product()
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    TelegramNotifier(TOKEN, "42").price_changed(product, change_for(product, "100.00", "120.00"))

    assert json.loads(route.calls.last.request.content)["text"] == (
        "📈 Price went up\n"
        "https://shop.example/item/1\n"
        "100.00 → 120.00 (+20.00%)\n"
        "https://shop.example/item/1"
    )


@respx.mock(assert_all_called=False)
def test_first_price_is_not_sent():
    product = make_product()
    route = respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    TelegramNotifier(TOKEN, "42").price_changed(product, change_for(product, None, "100.00"))

    assert not route.called


@respx.mock
def test_successful_send_does_not_log_the_token(caplog):
    # httpx logs "HTTP Request: POST <url>" at INFO, and the URL contains the bot token.
    product = make_product()
    respx.post(SEND_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    with caplog.at_level(logging.INFO):
        TelegramNotifier(TOKEN, "42").price_changed(product, change_for(product, "1", "2"))

    assert TOKEN not in caplog.text


@respx.mock
def test_api_error_does_not_leak_the_token():
    product = make_product()
    respx.post(SEND_URL).mock(return_value=httpx.Response(500, json={"ok": False}))

    with pytest.raises(NotificationError) as excinfo:
        TelegramNotifier(TOKEN, "42").price_changed(product, change_for(product, "1", "2"))

    assert str(excinfo.value) == "Telegram API returned HTTP 500"
    assert TOKEN not in str(excinfo.value)
    assert excinfo.value.__suppress_context__ is True


@respx.mock
def test_network_error_does_not_leak_the_token():
    product = make_product()
    respx.post(SEND_URL).mock(side_effect=httpx.ConnectError(f"cannot reach {SEND_URL}"))

    with pytest.raises(NotificationError) as excinfo:
        TelegramNotifier(TOKEN, "42").price_changed(product, change_for(product, "1", "2"))

    assert str(excinfo.value) == "Telegram API request failed: ConnectError"
