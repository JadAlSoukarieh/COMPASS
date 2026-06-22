from __future__ import annotations

from datetime import date
from random import Random

from sqlalchemy import delete, select

from backend.app.db import session_scope
from backend.app.models import Employee, LeaveBalance, LeaveRequest, User, UserRole
from backend.app.schema import bootstrap_schema
from data.seed.synthetic_data import (
    _leave_balances_for_employee,
    _leave_requests_for_employee,
    generate_synthetic_dataset,
)


def main(employee_count: int = 60, seed: int = 7) -> None:
    bootstrap_schema()

    with session_scope("admin") as session:
        session.execute(delete(LeaveRequest))
        session.execute(delete(LeaveBalance))

        protected_employee_ids = set(
            session.scalars(
                select(User.employee_id).where(
                    User.employee_id.is_not(None),
                    User.role.in_([UserRole.HR, UserRole.MGR, UserRole.EMP]),
                )
            ).all()
        )
        protected_names = {
            name
            for name in session.scalars(
                select(Employee.full_name).where(Employee.id.in_(protected_employee_ids))
            ).all()
            if name
        }

        dataset = generate_synthetic_dataset(
            employee_count=employee_count,
            seed=seed,
            reserved_names=protected_names,
        )

        if protected_employee_ids:
            session.execute(delete(Employee).where(Employee.id.not_in(protected_employee_ids)))
        else:
            session.execute(delete(Employee))
        session.flush()

        existing_employee_ids = set(session.scalars(select(Employee.id)).all())
        next_employee_id = max(existing_employee_ids, default=0) + 1
        employee_id_map: dict[int, int] = {}

        for employee in dataset.employees:
            if employee.id in protected_employee_ids:
                employee_id_map[employee.id] = employee.id
                continue

            old_id = employee.id
            employee.id = next_employee_id
            employee_id_map[old_id] = next_employee_id
            next_employee_id += 1

        for employee in dataset.employees:
            if employee.id in protected_employee_ids:
                continue
            if employee.manager_id is not None:
                employee.manager_id = employee_id_map.get(employee.manager_id, employee.manager_id)
            session.add(employee)

        session.flush()

        for balance in dataset.leave_balances:
            if balance.employee_id in protected_employee_ids:
                continue
            balance.employee_id = employee_id_map[balance.employee_id]
            session.add(balance)

        for request in dataset.leave_requests:
            if request.employee_id in protected_employee_ids:
                continue
            request.employee_id = employee_id_map[request.employee_id]
            if request.approver_id is not None:
                request.approver_id = employee_id_map.get(request.approver_id, request.approver_id)
            session.add(request)

        protected_employees = session.scalars(
            select(Employee).where(Employee.id.in_(protected_employee_ids)).order_by(Employee.id)
        ).all()
        for employee in protected_employees:
            for balance in _leave_balances_for_employee(employee=employee, year=date.today().year, seed=seed):
                session.add(balance)
            protected_rng_seed = seed + int(employee.id) * 1000
            for request in _leave_requests_for_employee(
                employee=employee,
                today=date.today(),
                seed=seed,
                rng=Random(protected_rng_seed),
            ):
                session.add(request)


if __name__ == "__main__":
    main()
