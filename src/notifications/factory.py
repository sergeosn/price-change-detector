from notifications.base import Notifier, NullNotifier


def get_notifier() -> Notifier:
    """Return the notifier configured in settings."""
    return NullNotifier()
