from notifications.base import NullNotifier
from notifications.factory import get_notifier


def test_null_notifier_does_nothing():
    assert NullNotifier().price_changed(product=None, change=None) is None


def test_notifications_are_off_by_default():
    assert isinstance(get_notifier(), NullNotifier)
