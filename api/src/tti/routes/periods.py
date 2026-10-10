from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException, Request

from tti.domain.timezone import today_for
from tti.routes.auth import get_current_session

router = APIRouter()


@router.get("/periods")
async def list_periods(request: Request) -> list[dict[str, object]]:
    session = await get_current_session(request)
    service = request.app.state.app_state["period_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})

    today = today_for(session.timezone, datetime.datetime.now(datetime.UTC))
    months = await service.months_for(session.employee_id, today)
    return [{"month": m.month, "state": m.state.value} for m in months]
