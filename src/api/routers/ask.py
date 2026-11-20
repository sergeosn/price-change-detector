from fastapi import APIRouter

from api.deps import AnswererDep, EmbedderDep
from api.schemas import AskRequest, AskResponse
from tracker.services import ask as service

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("")
def ask(body: AskRequest, embedder: EmbedderDep, answerer: AnswererDep) -> AskResponse:
    result = service.ask(body.question, body.limit, embedder=embedder, answerer=answerer)
    return AskResponse.from_result(result)
