from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.cache import get_cache
from backend.app.db import get_app_session, get_writer_session
from backend.app.models import Employee
from backend.app.schemas.employees import EmployeeCreate, EmployeePatch, EmployeeResponse
from backend.app.security.auth import AuthenticatedUser, require_roles

router = APIRouter(tags=["employees"])
templates = Jinja2Templates(directory="frontend/templates")


def _employee_response(employee: Employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee.id,
        full_name=employee.full_name,
        department=employee.department,
        grade=employee.grade,
        manager_id=employee.manager_id,
        hire_date=employee.hire_date,
        contract_end_date=employee.contract_end_date,
        salary=float(employee.salary),
        status=employee.status,
    )


def _validate_manager(session: Session, manager_id: int | None, *, employee_id: int | None = None) -> None:
    if manager_id is None:
        return
    if employee_id is not None and manager_id == employee_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Employee cannot manage themselves.")
    if session.get(Employee, manager_id) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Manager not found.")


def _bust_dashboard_cache(request: Request) -> int:
    try:
        cache = getattr(request.app.state, "cache", None) or get_cache()
        return int(cache.bust_namespace("dash"))
    except Exception:
        return 0


@router.get("/manage-employees", response_class=HTMLResponse, include_in_schema=False)
def manage_employees_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="manage_employees.html",
        context={"page_title": "Manage Employees · Compass"},
    )


@router.get("/employees", response_model=list[EmployeeResponse], status_code=status.HTTP_200_OK)
def list_employees(
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_app_session),
) -> list[EmployeeResponse]:
    employees = session.scalars(select(Employee).order_by(Employee.full_name, Employee.id)).all()
    return [_employee_response(employee) for employee in employees]


@router.post("/employees", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    request: Request,
    payload: EmployeeCreate,
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_writer_session),
) -> EmployeeResponse:
    _validate_manager(session, payload.manager_id)
    employee = Employee(**payload.model_dump())
    session.add(employee)
    session.flush()
    busted_keys = _bust_dashboard_cache(request)
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "create_employee",
            "employee_id": employee.id,
            "dashboard_cache_busted": busted_keys,
        },
    )
    return _employee_response(employee)


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse, status_code=status.HTTP_200_OK)
def patch_employee(
    employee_id: int,
    request: Request,
    payload: EmployeePatch,
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_writer_session),
) -> EmployeeResponse:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "manager_id" in updates:
        _validate_manager(session, updates["manager_id"], employee_id=employee.id)
    for field, value in updates.items():
        setattr(employee, field, value)

    session.flush()
    busted_keys = _bust_dashboard_cache(request)
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "patch_employee",
            "employee_id": employee.id,
            "fields": sorted(updates),
            "dashboard_cache_busted": busted_keys,
        },
    )
    return _employee_response(employee)
