"""Data model: shops (DomainRule), tracked products, price history and page text."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, URLValidator
from django.db import models
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from tracker.currencies import validate_currency_code
from tracker.domains import normalize_domain


class DomainRule(models.Model):
    """Shop settings: currency of every product on the domain and an optional selector."""

    domain = models.CharField("domain", max_length=255, unique=True)
    currency = models.CharField(
        "currency",
        max_length=3,
        blank=True,
        validators=[validate_currency_code],
        help_text="ISO 4217 code, e.g. UAH, USD, CAD.",
    )
    price_selector = models.CharField("price CSS selector", max_length=500, blank=True)
    created_at = models.DateTimeField("created at", auto_now_add=True)
    updated_at = models.DateTimeField("updated at", auto_now=True)

    class Meta:
        ordering = ["domain"]
        verbose_name = "domain rule"
        verbose_name_plural = "domain rules"

    def __str__(self) -> str:
        return self.domain

    def save(self, *args, **kwargs):
        self._normalize()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        self._normalize()
        if not self.domain:
            raise ValidationError({"domain": "Enter a valid domain, e.g. shop.example."})

    def _normalize(self) -> None:
        self.domain = normalize_domain(self.domain)
        self.currency = self.currency.strip().upper()

    @classmethod
    def currency_for(cls, domain: str) -> str:
        """Currency configured for the shop, '' if unknown."""
        return cls.objects.filter(domain=domain).values_list("currency", flat=True).first() or ""


class CheckStatus(models.TextChoices):
    NEVER = "never", "never checked"
    OK = "ok", "ok"
    ERROR = "error", "error"


class ProductQuerySet(models.QuerySet):
    def with_currency(self) -> "ProductQuerySet":
        """Annotate every product with `currency` taken from its DomainRule ('' if none)."""
        currency = DomainRule.objects.filter(domain=OuterRef("domain")).values("currency")[:1]
        return self.annotate(currency=Coalesce(Subquery(currency), Value("")))


class Product(models.Model):
    url = models.URLField(
        "URL",
        max_length=2048,
        unique=True,
        validators=[URLValidator(schemes=["http", "https"])],
    )
    # Derived from url in save(); stored so the currency can be joined in one query.
    domain = models.CharField("domain", max_length=255, editable=False, db_index=True)
    name = models.CharField("name", max_length=255, blank=True)
    price_selector = models.CharField(
        "price CSS selector",
        max_length=500,
        blank=True,
        help_text="If set, takes priority over the domain rule selector.",
    )
    target_price = models.DecimalField(
        "target price",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    current_price = models.DecimalField(
        "current price", max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField("tracking enabled", default=True)
    last_checked_at = models.DateTimeField("last checked at", null=True, blank=True)
    last_check_status = models.CharField(
        "status", max_length=10, choices=CheckStatus.choices, default=CheckStatus.NEVER
    )
    last_error = models.TextField("last error", blank=True)
    created_at = models.DateTimeField("created at", auto_now_add=True)
    updated_at = models.DateTimeField("updated at", auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "product"
        verbose_name_plural = "products"

    def __str__(self) -> str:
        return self.name or self.url

    def save(self, *args, **kwargs):
        self.domain = normalize_domain(self.url)
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and self.domain:
            # Register the shop so its currency and selector can be configured right away.
            DomainRule.objects.get_or_create(domain=self.domain)


class PriceChange(models.Model):
    """One detected price change. The first record of a product has old_price=None."""

    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="price_changes", verbose_name="product"
    )
    old_price = models.DecimalField(
        "old price", max_digits=12, decimal_places=2, null=True, blank=True
    )
    new_price = models.DecimalField("new price", max_digits=12, decimal_places=2)
    detected_at = models.DateTimeField("detected at")

    class Meta:
        ordering = ["-detected_at", "-id"]
        indexes = [models.Index(fields=["product", "detected_at"])]
        verbose_name = "price change"
        verbose_name_plural = "price history"

    def __str__(self) -> str:
        old_price = "—" if self.old_price is None else self.old_price
        return f"{self.product}: {old_price} → {self.new_price}"


class ProductDocument(models.Model):
    """Text of a product page kept for retrieval: one document per product."""

    product = models.OneToOneField(
        Product, on_delete=models.CASCADE, related_name="document", verbose_name="product"
    )
    title = models.CharField("title", max_length=255, blank=True)
    text = models.TextField("text")
    # SHA-256 of title and text: chunks are rebuilt only when it changes.
    content_hash = models.CharField("content hash", max_length=64)
    fetched_at = models.DateTimeField("fetched at")

    class Meta:
        ordering = ["-fetched_at", "-id"]
        verbose_name = "product document"
        verbose_name_plural = "product documents"

    def __str__(self) -> str:
        return self.title or str(self.product)


class Chunk(models.Model):
    """A piece of a document's text; `ordinal` is its position, starting at 0."""

    document = models.ForeignKey(
        ProductDocument, on_delete=models.CASCADE, related_name="chunks", verbose_name="document"
    )
    ordinal = models.PositiveIntegerField("ordinal")
    text = models.TextField("text")

    class Meta:
        ordering = ["document_id", "ordinal"]
        constraints = [
            models.UniqueConstraint(fields=["document", "ordinal"], name="unique_chunk_ordinal")
        ]
        verbose_name = "chunk"
        verbose_name_plural = "chunks"

    def __str__(self) -> str:
        return f"{self.document} #{self.ordinal}"
