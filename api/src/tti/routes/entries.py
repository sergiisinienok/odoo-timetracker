from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from tti.audit.service import record as record_audit
from tti.entries.service import CreatedEntry
from tti.errors import AppError
from tti.routes.auth import get_current_session

router = APIRouter()


class CreateEntryRequest(BaseModel):
    assignment_id: str
    date: str
    hours: float
    note: str = ""


class UpdateEntryRequest(BaseModel):
    assignment_id: str
    date: str
    hours: float
    note: str = ""


_ERROR_STATUS = {
    "assignment_not_held": 403,
    "invalid_increment": 400,
    "assignment_not_valid_on_date": 400,
    "period_locked": 409,
    "odoo_rejected": 422,
    "daily_cap_exceeded": 400,
    "entry_not_owned": 403,
}


def _serialize(entry: CreatedEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "outbox_id": entry.outbox_id,
        "assignment_id": entry.assignment_id,
        "date": entry.date,
        "hours": entry.hours,
        "note": entry.note,
        "project_id": entry.project_id,
        "so_line_id": entry.so_line_id,
        "sync_state": entry.sync_state,
    }


class _Outcome:
    value = "error"  # what gets recorded if the body exits without setting one


@asynccontextmanager
async def _audited(request: Request, employee_id: int, action: str, target: str):
    """Records one audit_log row per mutation attempt — allowed, refused or
    crashed — after it settles. Refusals record the error code (AppError),
    anything else records "error" and still propagates."""
    outcome = _Outcome()
    try:
        yield outcome
    except AppError as exc:
        outcome.value = exc.code
        raise
    finally:
        await record_audit(
            request.app.state.app_state["session_factory"],
            employee_id=employee_id,
            action=action,
            target=target,
            outcome=outcome.value,
        )


def _get_entry_service(request: Request):
    service = request.app.state.app_state["entry_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})
    return service


@router.post("/entries")
async def create_entry(request: Request, body: CreateEntryRequest) -> JSONResponse:
    session = await get_current_session(request)
    service = _get_entry_service(request)

    try:
        async with _audited(request, session.employee_id, "entry.create", "new") as audit:
            entry = await service.create_entry(
                employee_id=session.employee_id,
                assignment_id=body.assignment_id,
                date=body.date,
                hours=body.hours,
                note=body.note,
            )
            audit.value = entry.sync_state
    except AppError as exc:
        status = _ERROR_STATUS.get(exc.code, 400)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc

    # 201 synced, 202 pending — Appendix B. A pending write isn't a
    # rejection, it's the outbox's whole reason to exist: the request
    # succeeded from the employee's point of view, Odoo just hasn't
    # confirmed it yet.
    status_code = 201 if entry.sync_state == "synced" else 202
    return JSONResponse(status_code=status_code, content=_serialize(entry))


@router.patch("/entries/{entry_id}")
async def update_entry(request: Request, entry_id: int, body: UpdateEntryRequest) -> JSONResponse:
    session = await get_current_session(request)
    service = _get_entry_service(request)

    try:
        async with _audited(request, session.employee_id, "entry.update", str(entry_id)) as audit:
            entry = await service.update_entry(
                employee_id=session.employee_id,
                odoo_line_id=entry_id,
                assignment_id=body.assignment_id,
                date=body.date,
                hours=body.hours,
                note=body.note,
            )
            audit.value = entry.sync_state
    except AppError as exc:
        status = _ERROR_STATUS.get(exc.code, 400)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc

    status_code = 200 if entry.sync_state == "synced" else 202
    return JSONResponse(status_code=status_code, content=_serialize(entry))


@router.delete("/entries/{entry_id}")
async def delete_entry(request: Request, entry_id: int) -> Response:
    session = await get_current_session(request)
    service = _get_entry_service(request)

    try:
        async with _audited(request, session.employee_id, "entry.delete", str(entry_id)) as audit:
            sync_state = await service.delete_entry(employee_id=session.employee_id, odoo_line_id=entry_id)
            audit.value = sync_state
    except AppError as exc:
        status = _ERROR_STATUS.get(exc.code, 400)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc

    if sync_state == "synced":
        return Response(status_code=204)
    return JSONResponse(status_code=202, content={"sync_state": "pending"})


@router.get("/entries")
async def list_entries(request: Request, month: str | None = None) -> list[dict[str, object]]:
    session = await get_current_session(request)
    service = _get_entry_service(request)

    # Defaults to the current month in the employee's own timezone (step
    # 1.3's own reason for putting timezone in the session), not the
    # server's.
    if month is None:
        today = datetime.datetime.now(ZoneInfo(session.timezone)).date()
        year, month_num = today.year, today.month
    else:
        year_str, month_str = month.split("-")
        year, month_num = int(year_str), int(month_str)

    entries = await service.list_for_employee_month(session.employee_id, year, month_num)
    return [_serialize(e) for e in entries]


@router.get("/entries/search")
async def search_entries(
    request: Request,
    month: str | None = None,
    assignment_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    session = await get_current_session(request)
    service = _get_entry_service(request)

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    try:
        entries, total = await service.search(
            employee_id=session.employee_id,
            month=month,
            assignment_id=assignment_id,
            q=q,
            limit=limit,
            offset=offset,
        )
    except AppError as exc:
        status = _ERROR_STATUS.get(exc.code, 400)
        raise HTTPException(status_code=status, detail={"error": exc.code, "message": str(exc)}) from exc

    return {"items": [_serialize(e) for e in entries], "total": total}
