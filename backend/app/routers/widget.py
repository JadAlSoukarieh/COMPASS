from time import perf_counter

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.catalog import CatalogValidationError, execute_catalog_plan, validate_catalog_selection
from backend.app.db import get_app_session
from backend.app.llm.analyze import analyze_dashboard_rows
from backend.app.llm.intent import classify_intent, select_catalog
from backend.app.llm.query import phrase_catalog_answer
from backend.app.llm.support import answer_app_support
from backend.app.routers.dashboards import _dashboard_rows, _get_visible_dashboard
from backend.app.routers.auth import limiter
from backend.app.schemas.widget import WidgetMessageRequest, WidgetMessageResponse
from backend.app.security.auth import AuthenticatedUser, get_current_user
from backend.app.security.guards import GuardrailViolation, input_guard, output_guard

router = APIRouter(prefix="/widget", tags=["widget"])

WidgetMessageRequest.model_rebuild()
WidgetMessageResponse.model_rebuild()


def _audit_widget(
    *,
    action_type: str,
    current_user: AuthenticatedUser,
    result_status: str,
    detail: dict,
    session: Session,
    persist: bool = False,
) -> None:
    write_audit(
        action_type=action_type,
        role=current_user.role.value,
        result_status=result_status,
        user_id=current_user.user_id,
        detail=detail,
        session=session,
    )
    if persist:
        session.commit()


@router.post("/message", response_model=WidgetMessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
def widget_message(
    request: Request,
    payload: WidgetMessageRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> WidgetMessageResponse:
    started_at = perf_counter()
    try:
        message = input_guard(payload.message)
    except GuardrailViolation as exc:
        _audit_widget(
            action_type="guardrail_block",
            current_user=current_user,
            result_status="blocked",
            detail={"message": payload.message, "reason": exc.reason},
            session=session,
            persist=True,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc

    intent = classify_intent(
        message,
        page=payload.context.page,
        dashboard_id=payload.context.dashboard_id,
    )
    latency_ms = int((perf_counter() - started_at) * 1000)

    if intent == "refuse":
        answer = output_guard(
            {
                "answer_markdown": "I can help with company data questions and app how-to questions only.",
                "refused": True,
            },
            mode="plain",
        )
        _audit_widget(
            action_type="support",
            current_user=current_user,
            result_status="refused",
            detail={"intent": intent, "latency_ms": latency_ms, "scope_decision": "refused"},
            session=session,
        )
        return WidgetMessageResponse(
            intent="refuse",
            answer_markdown=answer["answer_markdown"],
            catalog_id=None,
            used_params={},
            scope_decision="refused",
            sources=[],
            refused=True,
        )

    if intent == "data_analysis":
        if payload.context.dashboard_id:
            dashboard = _get_visible_dashboard(payload.context.dashboard_id, current_user)
            rows, scope, cached = _dashboard_rows(
                request=request,
                dashboard=dashboard,
                current_user=current_user,
                session=session,
            )
            answer_markdown = analyze_dashboard_rows(
                dashboard_id=dashboard.id,
                title=dashboard.title,
                scope=scope,
                rows=rows,
            )
            guarded = output_guard({"answer_markdown": answer_markdown, "refused": False}, mode="plain")
            latency_ms = int((perf_counter() - started_at) * 1000)
            _audit_widget(
                action_type="data_analysis",
                current_user=current_user,
                result_status="success",
                detail={
                    "intent": intent,
                    "dashboard_id": dashboard.id,
                    "catalog_id": dashboard.catalog_id,
                    "scope": scope,
                    "row_count": len(rows),
                    "cached": cached,
                    "latency_ms": latency_ms,
                },
                session=session,
            )
            return WidgetMessageResponse(
                intent="data_analysis",
                answer_markdown=guarded["answer_markdown"],
                catalog_id=dashboard.catalog_id,
                used_params=dashboard.default_params,
                scope_decision="scoped" if scope in {"self", "team"} else "allowed",
                sources=[],
                refused=False,
            )

        answer = output_guard(
            {
                "answer_markdown": "Open a dashboard first, then use the dashboard analyze action or ask from that dashboard context.",
                "refused": True,
            },
            mode="plain",
        )
        _audit_widget(
            action_type="data_analysis",
            current_user=current_user,
            result_status="refused",
            detail={"intent": intent, "latency_ms": latency_ms, "scope_decision": "refused"},
            session=session,
        )
        return WidgetMessageResponse(
            intent="data_analysis",
            answer_markdown=answer["answer_markdown"],
            catalog_id=None,
            used_params={},
            scope_decision="refused",
            sources=[],
            refused=True,
        )

    if intent == "app_support":
        support = answer_app_support(message)
        guarded = output_guard(
            {
                "answer_markdown": support["answer_markdown"],
                "refused": support["refused"],
            },
            mode="plain",
        )
        latency_ms = int((perf_counter() - started_at) * 1000)
        _audit_widget(
            action_type="support",
            current_user=current_user,
            result_status="refused" if support["refused"] else "success",
            detail={
                "intent": intent,
                "latency_ms": latency_ms,
                "scope_decision": "allowed",
                "source_chunk_ids": [item["chunk_id"] for item in support["sources"]],
            },
            session=session,
        )
        return WidgetMessageResponse(
            intent="app_support",
            answer_markdown=guarded["answer_markdown"],
            catalog_id=None,
            used_params={},
            scope_decision="allowed",
            sources=support["sources"],
            refused=support["refused"],
        )

    selection = select_catalog(message)
    catalog_id = selection.get("catalog_id")
    params = selection.get("params")
    if not isinstance(catalog_id, str):
        _audit_widget(
            action_type="data_query",
            current_user=current_user,
            result_status="refused",
            detail={"intent": intent, "latency_ms": latency_ms, "scope_decision": "refused", "reason": "invalid_selection_shape"},
            session=session,
            persist=True,
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid_selection_shape")

    try:
        plan = validate_catalog_selection(
            catalog_id,
            params if isinstance(params, dict) else {},
            current_user=current_user,
            session=session,
        )
    except CatalogValidationError as exc:
        if str(exc) in {"employee_scope_refused", "catalog_role_forbidden"}:
            answer = output_guard(
                {
                    "answer_markdown": "I can't access that data within your current role and scope.",
                    "refused": True,
                },
                mode="plain",
            )
            _audit_widget(
                action_type="data_query",
                current_user=current_user,
                result_status="refused",
                detail={
                    "intent": intent,
                    "catalog_id": catalog_id,
                    "params": params if isinstance(params, dict) else {},
                    "scope_decision": "refused",
                    "reason": str(exc),
                    "latency_ms": int((perf_counter() - started_at) * 1000),
                },
                session=session,
            )
            return WidgetMessageResponse(
                intent="data_query",
                answer_markdown=answer["answer_markdown"],
                catalog_id=catalog_id,
                used_params=params if isinstance(params, dict) else {},
                scope_decision="refused",
                sources=[],
                refused=True,
            )
        if str(exc) in {"ambiguous_employee_name", "unknown_employee_name", "employee_id_name_mismatch"}:
            answer_text = {
                "ambiguous_employee_name": "I found multiple employees with that name. Please add the employee id, grade, or department.",
                "unknown_employee_name": "I couldn't match that employee name in your visible scope. Please check the spelling or use the employee id.",
                "employee_id_name_mismatch": "The employee id and employee name did not match the same record.",
            }[str(exc)]
            answer = output_guard(
                {
                    "answer_markdown": answer_text,
                    "refused": True,
                },
                mode="plain",
            )
            _audit_widget(
                action_type="data_query",
                current_user=current_user,
                result_status="refused",
                detail={
                    "intent": intent,
                    "catalog_id": catalog_id,
                    "params": params if isinstance(params, dict) else {},
                    "scope_decision": "refused",
                    "reason": str(exc),
                    "latency_ms": int((perf_counter() - started_at) * 1000),
                },
                session=session,
            )
            return WidgetMessageResponse(
                intent="data_query",
                answer_markdown=answer["answer_markdown"],
                catalog_id=catalog_id,
                used_params=params if isinstance(params, dict) else {},
                scope_decision="refused",
                sources=[],
                refused=True,
            )
        _audit_widget(
            action_type="data_query",
            current_user=current_user,
            result_status="refused",
            detail={
                "intent": intent,
                "catalog_id": catalog_id,
                "params": params if isinstance(params, dict) else {},
                "scope_decision": "refused",
                "reason": str(exc),
                "latency_ms": int((perf_counter() - started_at) * 1000),
            },
            session=session,
            persist=True,
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    rows = execute_catalog_plan(plan, session=session, current_user=current_user)
    answer_markdown = phrase_catalog_answer(
        message,
        catalog_id=plan.entry.id,
        formatter_hint=plan.entry.formatter_hint,
        rows=rows,
    )
    guarded = output_guard({"answer_markdown": answer_markdown, "refused": False}, mode="plain")
    latency_ms = int((perf_counter() - started_at) * 1000)
    _audit_widget(
        action_type="data_query",
        current_user=current_user,
        result_status="success",
        detail={
            "intent": intent,
            "catalog_id": plan.entry.id,
            "params": plan.params,
            "scope_decision": plan.scope_decision,
            "latency_ms": latency_ms,
            "row_count": len(rows),
        },
        session=session,
    )
    return WidgetMessageResponse(
        intent="data_query",
        answer_markdown=guarded["answer_markdown"],
        catalog_id=plan.entry.id,
        used_params=plan.params,
        scope_decision="scoped" if plan.scope_decision == "scoped" else "allowed",
        sources=[],
        refused=False,
    )
