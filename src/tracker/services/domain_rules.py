"""DomainRule operations used by the API."""

from django.db import IntegrityError, transaction

from tracker.models import DomainRule
from tracker.services.errors import DuplicateError, NotFoundError


def list_domain_rules(*, limit: int, offset: int) -> tuple[list[DomainRule], int]:
    rules = DomainRule.objects.all()
    return list(rules[offset : offset + limit]), rules.count()


def get_domain_rule(rule_id: int) -> DomainRule:
    try:
        return DomainRule.objects.get(pk=rule_id)
    except DomainRule.DoesNotExist:
        raise NotFoundError(f"Domain rule {rule_id} not found") from None


def create_domain_rule(*, domain: str, currency: str = "", price_selector: str = "") -> DomainRule:
    rule = DomainRule(domain=domain, currency=currency, price_selector=price_selector)
    _save(rule)
    return rule


def update_domain_rule(rule_id: int, changes: dict[str, object]) -> DomainRule:
    rule = get_domain_rule(rule_id)
    for field, value in changes.items():
        setattr(rule, field, value)
    _save(rule)
    return rule


def delete_domain_rule(rule_id: int) -> None:
    get_domain_rule(rule_id).delete()


def _save(rule: DomainRule) -> None:
    try:
        with transaction.atomic():
            rule.save()
    except IntegrityError:
        raise DuplicateError(f"Domain rule for {rule.domain} already exists") from None
