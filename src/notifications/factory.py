from django.conf import settings

from notifications.base import Notifier, NullNotifier
from notifications.telegram import TelegramNotifier


def get_notifier() -> Notifier:
    """Telegram when both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set, else no-op."""
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        return TelegramNotifier(
            token=settings.TELEGRAM_BOT_TOKEN, chat_id=settings.TELEGRAM_CHAT_ID
        )
    return NullNotifier()
