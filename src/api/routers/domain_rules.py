from fastapi import APIRouter, Response, status

from api.deps import PaginationDep
from api.schemas import DomainRuleCreate, DomainRuleOut, DomainRuleUpdate, Page
from tracker.services import domain_rules as service

router = APIRouter(prefix="/domain-rules", tags=["domain-rules"])


@router.get("")
def list_domain_rules(pagination: PaginationDep) -> Page[DomainRuleOut]:
    rules, total = service.list_domain_rules(limit=pagination.limit, offset=pagination.offset)
    return Page[DomainRuleOut](
        items=[DomainRuleOut.from_model(rule) for rule in rules],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_domain_rule(payload: DomainRuleCreate) -> DomainRuleOut:
    rule = service.create_domain_rule(
        domain=payload.domain, currency=payload.currency, price_selector=payload.price_selector
    )
    return DomainRuleOut.from_model(rule)


@router.get("/{rule_id}")
def get_domain_rule(rule_id: int) -> DomainRuleOut:
    return DomainRuleOut.from_model(service.get_domain_rule(rule_id))


@router.patch("/{rule_id}")
def update_domain_rule(rule_id: int, payload: DomainRuleUpdate) -> DomainRuleOut:
    rule = service.update_domain_rule(rule_id, payload.model_dump(exclude_unset=True))
    return DomainRuleOut.from_model(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_domain_rule(rule_id: int) -> Response:
    service.delete_domain_rule(rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
