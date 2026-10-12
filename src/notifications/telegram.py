"""Telegram notifications through the Bot API (sendMessage)."""

from decimal import ROUND_HALF_UP, Decimal

import httpx

from notifications.base import NotificationError
from tracker.models import DomainRule, PriceChange, Product

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def price_changed(self, product: Product, change: PriceChange) -> None:
        if change.old_price is None:
            return  # the first recorded price is not a change
        text = format_message(product, change, DomainRule.currency_for(product.domain))
        try:
            response = httpx.post(
                API_URL.format(token=self.token),
                json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            response.raise_for_status()
        # httpx errors embed the request URL, which contains the bot token:
        # re-raise without them so the token never reaches logs.
        except httpx.HTTPStatusError as exc:
            raise NotificationError(
                f"Telegram API returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise NotificationError(
                f"Telegram API request failed: {exc.__class__.__name__}"
            ) from None


def format_message(product: Product, change: PriceChange, currency: str) -> str:
    old, new = change.old_price, change.new_price
    percent = ((new - old) / old * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    suffix = f" {currency}" if currency else ""
    target = product.target_price

    lines = []
    if target is not None and new <= target:
        lines.append("🎯 Target price reached!")
    lines.append("📉 Price dropped" if new < old else "📈 Price went up")
    lines.append(product.name or product.url)
    lines.append(f"{old:.2f} → {new:.2f}{suffix} ({percent:+.2f}%)")
    if target is not None:
        lines.append(f"Target price: {target:.2f}{suffix}")
    lines.append(product.url)
    return "\n".join(lines)
