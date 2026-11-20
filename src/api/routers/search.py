from typing import Annotated

from fastapi import APIRouter, Query

from api.deps import EmbedderDep
from api.schemas import SearchItemOut, SearchResponse
from tracker.services import search as service
from tracker.services.search import SearchMode

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    embedder: EmbedderDep,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    mode: SearchMode = SearchMode.HYBRID,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> SearchResponse:
    results = service.search(q, mode, limit, embedder=embedder)
    return SearchResponse(
        query=q, mode=mode, items=[SearchItemOut.from_result(result) for result in results]
    )
