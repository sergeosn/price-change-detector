from fastapi import APIRouter, Response
from fastapi import status as http_status

from api.deps import FetcherDep, NotifierDep, PaginationDep
from api.schemas import CheckStatusValue, Page, ProductCreate, ProductOut, ProductUpdate
from tracker.services import products as service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    pagination: PaginationDep,
    is_active: bool | None = None,
    status: CheckStatusValue | None = None,
) -> Page[ProductOut]:
    products, total = service.list_products(
        is_active=is_active, status=status, limit=pagination.limit, offset=pagination.offset
    )
    return Page[ProductOut](
        items=[ProductOut.from_model(product) for product in products],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post("", status_code=http_status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate, fetcher: FetcherDep, notifier: NotifierDep
) -> ProductOut:
    product = service.create_product(
        url=payload.url,
        name=payload.name,
        price_selector=payload.price_selector,
        target_price=payload.target_price,
        is_active=payload.is_active,
    )
    if payload.check_now:
        _, product = service.run_check(product.pk, fetcher=fetcher, notifier=notifier)
    return ProductOut.from_model(product)


@router.get("/{product_id}")
def get_product(product_id: int) -> ProductOut:
    return ProductOut.from_model(service.get_product(product_id))


@router.patch("/{product_id}")
def update_product(product_id: int, payload: ProductUpdate) -> ProductOut:
    product = service.update_product(product_id, payload.model_dump(exclude_unset=True))
    return ProductOut.from_model(product)


@router.delete(
    "/{product_id}", status_code=http_status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_product(product_id: int) -> Response:
    service.delete_product(product_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
