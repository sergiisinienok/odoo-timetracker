from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tti.entries.errors import EntryError
from tti.routes.auth import get_current_session

router = APIRouter()


class CreateEntryRequest(BaseModel):
    assignment_id: str
    date: str
    hours: float
    note: str = ""


_ERROR_STATUS = {
    "assignment_not_held": 403,
    "invalid_increment": 400,
    "assignment_not_valid_on_date": 400,
}


@router.post("/entries", status_code=201)
async def create_entry(request: Request, body: CreateEntryRequest) -> dict[str, object]:
    session = await get_current_session(request)
    service = request.app.state.app_state["entry_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})

    try:
        entry = await service.create_entry(
            employee_id=session.employee_id,
            assignment_id=body.assignment_id,
            date=body.date,
            hours=body.hours,
            note=body.note,
        )
    except EntryError as exc:
        status = _ERROR_STATUS.get(exc.code, 400)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc

    return {
        "id": entry.id,
        "assignment_id": entry.assignment_id,
        "date": entry.date,
        "hours": entry.hours,
        "note": entry.note,
        "project_id": entry.project_id,
        "so_line_id": entry.so_line_id,
    }
