from __future__ import annotations

import os
from datetime import date

from sqlalchemy import select

from backend.app.db import session_scope
from backend.app.models import AuditLog, Employee, User, UserRole
from backend.app.schema import bootstrap_schema
from backend.app.security.auth import hash_password


DEMO_USERS = [
    {
        "username": "superuser",
        "env_var": "DEMO_PASSWORD_SUPERUSER",
        "role": UserRole.SUPERUSER,
        "employee": None,
    },
    {
        "username": "hr",
        "env_var": "DEMO_PASSWORD_HR",
        "role": UserRole.HR,
        "employee": {
            "full_name": "Hana Rahal",
            "department": "HR",
            "grade": "G7",
            "salary": 6500,
            "status": "active",
        },
    },
    {
        "username": "mgr",
        "env_var": "DEMO_PASSWORD_MGR",
        "role": UserRole.MGR,
        "employee": {
            "full_name": "Mazen Haddad",
            "department": "Operations",
            "grade": "G8",
            "salary": 7200,
            "status": "active",
        },
    },
    {
        "username": "emp",
        "env_var": "DEMO_PASSWORD_EMP",
        "role": UserRole.EMP,
        "employee": {
            "full_name": "Lina Nassar",
            "department": "Operations",
            "grade": "G5",
            "salary": 3200,
            "status": "active",
        },
    },
]


def _require_password(env_var: str) -> str:
    password = os.getenv(env_var, "").strip()
    if not password:
        raise RuntimeError(f"Missing required demo password env var: {env_var}")
    return password


def main() -> None:
    bootstrap_schema()

    with session_scope("admin") as session:
        manager_employee_id: int | None = None

        for spec in DEMO_USERS:
            user = session.scalar(select(User).where(User.username == spec["username"]))
            if user is not None:
                continue

            employee_id = None
            employee_spec = spec["employee"]
            if employee_spec is not None:
                employee = Employee(
                    full_name=employee_spec["full_name"],
                    department=employee_spec["department"],
                    grade=employee_spec["grade"],
                    manager_id=manager_employee_id if spec["role"] == UserRole.EMP else None,
                    hire_date=date(2024, 1, 1),
                    contract_end_date=None,
                    salary=employee_spec["salary"],
                    status=employee_spec["status"],
                )
                session.add(employee)
                session.flush()
                employee_id = employee.id
                if spec["role"] == UserRole.MGR:
                    manager_employee_id = employee.id

            session.add(
                User(
                    username=spec["username"],
                    password_hash=hash_password(_require_password(spec["env_var"])),
                    role=spec["role"],
                    employee_id=employee_id,
                    is_active=True,
                )
            )


if __name__ == "__main__":
    main()
