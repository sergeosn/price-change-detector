"""Price change notifications: the interface and the default no-op implementation."""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from tracker.models import PriceChange, Product


class Notifier(Protocol):
    def price_changed(self, product: "Product", change: "PriceChange") -> None:
        """Called after a new PriceChange has been committed."""
        ...


class NullNotifier:
    def price_changed(self, product: "Product", change: "PriceChange") -> None:
        return None
