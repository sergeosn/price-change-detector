from notifications.base import NullNotifier
from notifications.factory import get_notifier
from notifications.telegram import TelegramNotifier


def test_null_notifier_does_nothing():
    assert NullNotifier().price_changed(product=None, change=None) is None


def test_notifications_are_off_by_default():
    assert isinstance(get_notifier(), NullNotifier)


def test_telegram_is_used_when_configured(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.TELEGRAM_CHAT_ID = "42"
    notifier = get_notifier()
    assert isinstance(notifier, TelegramNotifier)
    assert (notifier.token, notifier.chat_id) == ("123:abc", "42")


def test_telegram_needs_both_token_and_chat(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.TELEGRAM_CHAT_ID = ""
    assert isinstance(get_notifier(), NullNotifier)
