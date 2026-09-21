from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tti.entries.errors import EntryError
from tti.entries.service import CreatedEntry
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


def _serialize(entry: CreatedEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "assignment_id": entry.assignment_id,
        "date": entry.date,
        "hours": entry.hours,
        "note": entry.note,
        "project_id": entry.project_id,
        "so_line_id": entry.so_line_id,
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

    return _serialize(entry)


@router.get("/entries")
async def list_entries(request: Request, date: str | None = None) -> list[dict[str, object]]:
    session = await get_current_session(request)
    service = request.app.state.app_state["entry_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})

    # "Today" means today in the employee's own timezone (step 1.3's own
    # reason for putting timezone in the session), not the server's.
    resolved_date = date or datetime.datetime.now(ZoneInfo(session.timezone)).date().isoformat()

    entries = await service.list_for_employee_on_date(session.employee_id, resolved_date)
    return [_serialize(e) for e in entries]
