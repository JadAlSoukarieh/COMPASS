from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from backend.app.catalog.registry import CATALOG_BY_ID, CatalogEntry, CatalogParam
from backend.app.models import Employee
from backend.app.security.auth import AuthenticatedUser
from backend.app.security.scope import ScopeContext, resolve_scope


class CatalogValidationError(ValueError):
    """Raised when catalog selection or params are invalid."""


@dataclass(slots=True)
class CatalogExecutionPlan:
    entry: CatalogEntry
    params: dict[str, Any]
    scope_decision: str
    scope_context: ScopeContext


def get_catalog_entry(catalog_id: str) -> CatalogEntry:
    entry = CATALOG_BY_ID.get(catalog_id)
    if entry is None:
        raise CatalogValidationError("unknown_catalog_id")
    return entry


def validate_catalog_selection(
    catalog_id: str,
    params: dict[str, Any] | None,
    *,
    current_user: AuthenticatedUser,
    session: Session,
) -> CatalogExecutionPlan:
    entry = get_catalog_entry(catalog_id)
    if current_user.role.value not in entry.required_roles:
        raise CatalogValidationError("catalog_role_forbidden")

    scope_context = resolve_scope(current_user, session)
    raw_params = params or {}
    validated_params = _validate_params(entry, raw_params, session=session, scope_context=scope_context)
    validated_params = _resolve_employee_selector(validated_params, session=session, scope_context=scope_context)
    final_params, scope_decision = _apply_scope(entry, validated_params, current_user=current_user, scope_context=scope_context)
    return CatalogExecutionPlan(
        entry=entry,
        params=_with_defaults(entry, final_params),
        scope_decision=scope_decision,
        scope_context=scope_context,
    )


def execute_catalog_plan(plan: CatalogExecutionPlan, *, session: Session, current_user: AuthenticatedUser) -> list[dict[str, Any]]:
    sql, params = _render_sql(plan, current_user=current_user)
    statement = text(sql)
    if ":allowed_employee_ids" in sql:
        statement = statement.bindparams(bindparam("allowed_employee_ids", expanding=True))
    rows = session.execute(statement, params).mappings().all()
    return [_normalize_row(dict(row)) for row in rows]


def _validate_params(
    entry: CatalogEntry,
    params: dict[str, Any],
    *,
    session: Session,
    scope_context: ScopeContext,
) -> dict[str, Any]:
    validated: dict[str, Any] = {}
    allowed_names = {param.name for param in entry.params}
    for name in params:
        if name not in allowed_names:
            raise CatalogValidationError(f"unknown_param:{name}")

    for param in entry.params:
        value = params.get(param.name)
        if value is None:
            if param.required:
                raise CatalogValidationError(f"missing_param:{param.name}")
            continue
        validated[param.name] = _coerce_param(param, value, session=session, scope_context=scope_context)
    return validated


def _coerce_param(param: CatalogParam, value: Any, *, session: Session, scope_context: ScopeContext) -> Any:
    if param.type == "int":
        try:
            coerced = int(value)
        except (TypeError, ValueError) as exc:
            raise CatalogValidationError(f"invalid_param_type:{param.name}") from exc
        if param.min_value is not None and coerced < param.min_value:
            raise CatalogValidationError(f"param_below_min:{param.name}")
        if param.max_value is not None and coerced > param.max_value:
            raise CatalogValidationError(f"param_above_max:{param.name}")
        if param.entity == "employee" and session.get(Employee, coerced) is None:
            raise CatalogValidationError(f"unknown_employee:{param.name}")
        return coerced

    if param.type == "str":
        coerced = " ".join(str(value).split()).strip()
        if not coerced:
            raise CatalogValidationError(f"invalid_param_value:{param.name}")
        if param.allowed_values and coerced not in param.allowed_values:
            raise CatalogValidationError(f"invalid_param_value:{param.name}")
        if param.entity == "department" and not _value_exists(Employee.department, coerced, session=session):
            raise CatalogValidationError(f"unknown_department:{param.name}")
        if param.entity == "grade" and not _value_exists(Employee.grade, coerced, session=session):
            raise CatalogValidationError(f"unknown_grade:{param.name}")
        if param.entity == "employee_status" and not _value_exists(Employee.status, coerced, session=session):
            raise CatalogValidationError(f"unknown_employee_status:{param.name}")
        if param.entity == "employee_name":
            visible_ids = _visible_employee_ids(scope_context)
            if not _employee_name_exists(coerced, session=session, visible_ids=visible_ids):
                raise CatalogValidationError("unknown_employee_name")
        return coerced

    raise CatalogValidationError(f"unsupported_param_type:{param.name}")


def _resolve_employee_selector(
    params: dict[str, Any],
    *,
    session: Session,
    scope_context: ScopeContext,
) -> dict[str, Any]:
    if "employee_name" not in params or params.get("employee_name") is None:
        return params

    resolved = dict(params)
    employee_name = str(resolved["employee_name"])
    visible_ids = _visible_employee_ids(scope_context)
    matched_ids = _find_employee_ids_by_name(
        employee_name,
        session=session,
        visible_ids=visible_ids,
        department=resolved.get("department"),
        grade=resolved.get("grade"),
    )
    explicit_employee_id = resolved.get("employee_id")

    if explicit_employee_id is not None:
        if explicit_employee_id not in matched_ids:
            raise CatalogValidationError("employee_id_name_mismatch")
        return resolved

    if not matched_ids:
        raise CatalogValidationError("unknown_employee_name")
    if len(matched_ids) > 1:
        raise CatalogValidationError("ambiguous_employee_name")

    resolved["employee_id"] = matched_ids[0]
    return resolved


def _apply_scope(
    entry: CatalogEntry,
    params: dict[str, Any],
    *,
    current_user: AuthenticatedUser,
    scope_context: ScopeContext,
) -> tuple[dict[str, Any], str]:
    resolved = dict(params)
    decision = "allowed"

    if entry.supports_employee_param and current_user.employee_id is not None:
        requested_employee_id = resolved.get("employee_id")
        if scope_context.scope == "self":
            if requested_employee_id is None or requested_employee_id == current_user.employee_id:
                resolved["employee_id"] = current_user.employee_id
                decision = "scoped" if requested_employee_id is None else "allowed"
            else:
                raise CatalogValidationError("employee_scope_refused")
        elif scope_context.scope == "team":
            allowed_ids = set(scope_context.allowed_employee_ids)
            if requested_employee_id is None:
                decision = "allowed"
            elif requested_employee_id not in allowed_ids:
                raise CatalogValidationError("employee_scope_refused")
        else:
            decision = "allowed"

    if scope_context.scope == "team" and entry.required_roles == ("hr", "superuser"):
        raise CatalogValidationError("catalog_role_forbidden")

    return resolved, decision


def _with_defaults(entry: CatalogEntry, params: dict[str, Any]) -> dict[str, Any]:
    resolved = {param.name: params.get(param.name) for param in entry.params}
    today = date.today()
    if "year" in {param.name for param in entry.params} and resolved.get("year") is None:
        resolved["year"] = today.year
    if "limit" in {param.name for param in entry.params} and resolved.get("limit") is None:
        resolved["limit"] = 5
    if "days_ahead" in {param.name for param in entry.params} and resolved.get("days_ahead") is None:
        resolved["days_ahead"] = 30
    if "days" in {param.name for param in entry.params} and resolved.get("days") is None:
        resolved["days"] = 90
    if "months" in {param.name for param in entry.params} and resolved.get("months") is None:
        resolved["months"] = 6
    if "min_remaining" in {param.name for param in entry.params} and resolved.get("min_remaining") is None:
        resolved["min_remaining"] = 10
    if resolved.get("months") is not None:
        resolved["lookback_days"] = int(resolved["months"]) * 30
    return resolved


def _render_sql(plan: CatalogExecutionPlan, *, current_user: AuthenticatedUser) -> tuple[str, dict[str, Any]]:
    params = dict(plan.params)
    params.pop("employee_name", None)
    scope_context = plan.scope_context
    if plan.entry.scope_column is None:
        scope_clause = "1=1"
    elif scope_context.scope == "self":
        if current_user.employee_id is None:
            raise CatalogValidationError("missing_employee_scope")
        params["scope_employee_id"] = current_user.employee_id
        scope_clause = f"{plan.entry.scope_column} = :scope_employee_id"
    elif scope_context.scope == "team":
        allowed_ids = scope_context.allowed_employee_ids or [-1]
        params["allowed_employee_ids"] = allowed_ids
        scope_clause = f"{plan.entry.scope_column} IN :allowed_employee_ids"
    else:
        scope_clause = "1=1"

    if plan.entry.id == "TEAM_PENDING_MY_APPROVAL":
        params["approver_id"] = current_user.employee_id

    return plan.entry.sql.format(scope_clause=scope_clause), params


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            normalized[key] = float(value)
        elif isinstance(value, date):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def _visible_employee_ids(scope_context: ScopeContext) -> list[int] | None:
    if scope_context.scope == "company":
        return None
    if scope_context.scope == "self":
        return [scope_context.employee_id] if scope_context.employee_id is not None else []
    return list(scope_context.allowed_employee_ids)


def _value_exists(column: Any, value: str, *, session: Session) -> bool:
    return session.scalar(select(column).where(column == value).limit(1)) is not None


def _employee_name_exists(name: str, *, session: Session, visible_ids: list[int] | None) -> bool:
    return bool(_find_employee_ids_by_name(name, session=session, visible_ids=visible_ids))


def _find_employee_ids_by_name(
    name: str,
    *,
    session: Session,
    visible_ids: list[int] | None,
    department: str | None = None,
    grade: str | None = None,
) -> list[int]:
    statement = select(Employee.id).where(func.lower(Employee.full_name) == name.lower())
    if department is not None:
        statement = statement.where(Employee.department == department)
    if grade is not None:
        statement = statement.where(Employee.grade == grade)
    if visible_ids is not None:
        if not visible_ids:
            return []
        statement = statement.where(Employee.id.in_(visible_ids))
    return list(session.scalars(statement.order_by(Employee.id)).all())
