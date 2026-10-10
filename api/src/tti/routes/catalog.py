from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from tti.routes.auth import get_current_session

router = APIRouter()


@router.get("/catalog")
async def get_catalog(request: Request) -> list[dict[str, object]]:
    """Projects and open tasks this employee may log against. Never carries
    billability, a rate or an amount (decision 0011)."""
    session = await get_current_session(request)
    service = request.app.state.app_state["catalog_service"]
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "profile_not_loaded"})

    catalog = await service.list_for_employee(session.employee_id)
    return [
        {
            "project_id": p.id,
            "label": p.label,
            "is_default": p.is_default,
            "last_used_task_id": p.last_used_task_id,
            "tasks": [{"id": t.id, "name": t.name} for t in p.tasks],
        }
        for p in catalog
    ]
