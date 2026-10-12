from django.contrib import admin, messages
from django.db import models
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import formats
from django.utils.html import format_html

from notifications.factory import get_notifier
from tracker.models import CheckStatus, DomainRule, PriceChange, Product
from tracker.services.checker import check_product
from tracker.services.fetcher import get_fetcher

admin.site.site_header = "Price Change Detector"
admin.site.site_title = "Price Change Detector"

STATUS_COLORS = {
    CheckStatus.NEVER: "#6c757d",
    CheckStatus.OK: "#28a745",
    CheckStatus.ERROR: "#dc3545",
}


def format_price(value, currency: str) -> str:
    if value is None:
        return "—"
    return f"{formats.number_format(value, decimal_pos=2)} {currency}".strip()


class PriceChangeInline(admin.TabularInline):
    model = PriceChange
    extra = 0
    can_delete = False
    fields = ("detected_at", "old_price", "new_price")
    readonly_fields = fields
    ordering = ("-detected_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "domain",
        "price_with_currency",
        "target_price",
        "status_badge",
        "last_checked_at",
        "is_active",
    )
    list_filter = ("last_check_status", "is_active")
    search_fields = ("name", "url")
    readonly_fields = (
        "domain",
        "currency_display",
        "current_price",
        "last_checked_at",
        "last_check_status",
        "last_error",
        "created_at",
        "updated_at",
    )
    inlines = [PriceChangeInline]
    actions = ["check_now", "enable_tracking", "disable_tracking"]
    # Keep Django's current default for scheme-less URLs and silence the Django 6.0 deprecation.
    formfield_overrides = {models.URLField: {"assume_scheme": "http"}}

    def get_queryset(self, request: HttpRequest) -> QuerySet[Product]:
        return super().get_queryset(request).with_currency()

    def get_readonly_fields(self, request: HttpRequest, obj=None):
        # A new URL means a new product with its own history.
        if obj is None:
            return self.readonly_fields
        return ("url", *self.readonly_fields)

    @admin.display(description="Name", ordering="name")
    def display_name(self, obj: Product) -> str:
        return obj.name or obj.url

    @admin.display(description="Current price", ordering="current_price")
    def price_with_currency(self, obj: Product) -> str:
        return format_price(obj.current_price, obj.currency)

    @admin.display(description="Currency")
    def currency_display(self, obj: Product) -> str:
        return obj.currency or "—"

    @admin.display(description="Status", ordering="last_check_status")
    def status_badge(self, obj: Product) -> str:
        return format_html(
            '<span class="status-badge status-{}" style="color:#fff;background:{};'
            'padding:2px 8px;border-radius:8px;">{}</span>',
            obj.last_check_status,
            STATUS_COLORS[obj.last_check_status],
            obj.get_last_check_status_display(),
        )

    @admin.action(description="Check now")
    def check_now(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        fetcher, notifier = get_fetcher(), get_notifier()
        results = [check_product(product, fetcher, notifier) for product in queryset]
        ok = sum(1 for result in results if result.status == "ok")
        errors = len(results) - ok
        self.message_user(
            request,
            f"Checked: {ok} succeeded, {errors} failed.",
            level=messages.SUCCESS if errors == 0 else messages.WARNING,
        )

    @admin.action(description="Enable tracking")
    def enable_tracking(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Tracking enabled: {updated}.")

    @admin.action(description="Disable tracking")
    def disable_tracking(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Tracking disabled: {updated}.")


@admin.register(DomainRule)
class DomainRuleAdmin(admin.ModelAdmin):
    list_display = ("domain", "currency", "price_selector", "updated_at")
    search_fields = ("domain",)


@admin.register(PriceChange)
class PriceChangeAdmin(admin.ModelAdmin):
    list_display = ("product", "old_price", "new_price", "detected_at")
    list_filter = ("product",)
    list_select_related = ("product",)
    ordering = ("-detected_at",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj=None) -> bool:
        return False
