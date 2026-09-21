from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tti.routes.auth import get_current_session

router = APIRouter()


@router.get("/assignments")
async def list_assignments(request: Request) -> list[dict[str, object]]:
    session = await get_current_session(request)
    service = request.app.state.app_state["assignment_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})

    assignments = await service.list_for_employee(session.employee_id)
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "project_id": a.project_id,
            "so_line_id": a.so_line_id,
            "label": a.label,
            "is_default": a.is_default,
            "start_date": a.start_date,
            "end_date": a.end_date,
        }
        for a in assignments
    ]
