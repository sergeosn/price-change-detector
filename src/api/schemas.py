"""Pydantic schemas of the public API. Mapping from Django models is explicit."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tracker.currencies import normalize_currency
from tracker.domains import normalize_domain
from tracker.models import DomainRule


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
