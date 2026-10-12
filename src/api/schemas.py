"""Pydantic schemas of the public API. Mapping from Django models is explicit."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from tracker.currencies import normalize_currency
from tracker.domains import normalize_domain
from tracker.models import DomainRule, Product

# Money goes over the wire as a string with exactly two decimals: "1299.00".
Money = Annotated[
    Decimal, PlainSerializer(lambda value: f"{value:.2f}", return_type=str, when_used="json")
]
PositivePrice = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
CheckStatusValue = Literal["never", "ok", "error"]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def clean_domain(value: str) -> str:
    domain = normalize_domain(value)
    if not domain:
        raise ValueError("Invalid domain")
    return domain


def clean_currency(value: str) -> str:
    if not value.strip():
        return ""
    code = normalize_currency(value)
    if code is None:
        raise ValueError("Unknown ISO 4217 currency code")
    return code


def not_null[V](value: V | None) -> V:
    if value is None:
        raise ValueError("Field may not be null")
    return value


def clean_url(value: str) -> str:
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL must be an absolute http(s) URL")
    return value


class DomainRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="", max_length=3)
    price_selector: str = Field(default="", max_length=500)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return clean_domain(value)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return clean_currency(value)


class DomainRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str | None = Field(default=None, min_length=1, max_length=255)
    currency: str | None = Field(default=None, max_length=3)
    price_selector: str | None = Field(default=None, max_length=500)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str | None) -> str:
        return clean_domain(not_null(value))

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str:
        return clean_currency(not_null(value))

    @field_validator("price_selector")
    @classmethod
    def validate_price_selector(cls, value: str | None) -> str:
        return not_null(value)


class DomainRuleOut(BaseModel):
    id: int
    domain: str
    currency: str
    price_selector: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, rule: DomainRule) -> Self:
        return cls(
            id=rule.pk,
            domain=rule.domain,
            currency=rule.currency,
            price_selector=rule.price_selector,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=2048)
    name: str = Field(default="", max_length=255)
    price_selector: str = Field(default="", max_length=500)
    target_price: PositivePrice | None = None
    is_active: bool = True
    check_now: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return clean_url(value)


class ProductUpdate(BaseModel):
    """Partial update. The URL is immutable: a new URL is a new product."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    price_selector: str | None = Field(default=None, max_length=500)
    target_price: PositivePrice | None = None
    is_active: bool | None = None

    @field_validator("name", "price_selector", "is_active")
    @classmethod
    def reject_null(cls, value: object) -> object:
        return not_null(value)


class ProductOut(BaseModel):
    id: int
    url: str
    domain: str
    name: str
    price_selector: str
    target_price: Money | None
    currency: str | None
    current_price: Money | None
    is_active: bool
    last_checked_at: datetime | None
    last_check_status: CheckStatusValue
    last_error: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, product: Product) -> Self:
        """`product` must come from Product.objects.with_currency()."""
        return cls(
            id=product.pk,
            url=product.url,
            domain=product.domain,
            name=product.name,
            price_selector=product.price_selector,
            target_price=product.target_price,
            currency=getattr(product, "currency", "") or None,
            current_price=product.current_price,
            is_active=product.is_active,
            last_checked_at=product.last_checked_at,
            last_check_status=product.last_check_status,
            last_error=product.last_error,
            created_at=product.created_at,
            updated_at=product.updated_at,
        )
