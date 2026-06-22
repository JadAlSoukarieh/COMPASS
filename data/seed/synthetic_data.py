from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import random

from backend.app.models import Employee, LeaveBalance, LeaveRequest


DEPARTMENTS = ("Operations", "Engineering", "HR", "Finance", "Sales", "Marketing", "Support")
GRADES = ("G3", "G4", "G5", "G6", "G7", "G8", "G9")
LEAVE_TYPES = ("annual", "sick", "unpaid")
LEAVE_STATUSES = ("pending", "approved", "rejected")
FIRST_NAMES = (
    "Lina", "Mazen", "Hana", "Omar", "Rana", "Nadim", "Mira", "Tariq", "Salma", "Jad",
    "Yara", "Rami", "Lea", "Karim", "Dana", "Sami", "Noor", "Rita", "Fadi", "Nour",
)
LAST_NAMES = (
    "Nassar", "Haddad", "Rahal", "Khalil", "Saade", "Helou", "Mansour", "Awad", "Shami", "Farah",
    "Saba", "Daher", "Makki", "Issa", "Kanaan", "Abouzeid", "Karam", "Zein", "Kassis", "Saliba",
)
PRIORITY_NAMES = ("Jad Karam",)
ALL_NAME_COMBINATIONS = tuple(f"{first} {last}" for last in LAST_NAMES for first in FIRST_NAMES)


@dataclass(slots=True)
class SyntheticDataset:
    employees: list[Employee]
    leave_balances: list[LeaveBalance]
    leave_requests: list[LeaveRequest]


def _build_name_sequence(*, employee_count: int, seed: int, reserved_names: set[str] | None = None) -> list[str]:
    reserved = {name.lower() for name in (reserved_names or set())}
    available = [name for name in ALL_NAME_COMBINATIONS if name.lower() not in reserved]
    if len(available) < employee_count:
        raise ValueError("not enough unique synthetic names available for the requested employee count")

    rng = random.Random(seed)
    priority = [name for name in PRIORITY_NAMES if name.lower() not in reserved and name in available]
    remaining = [name for name in available if name not in priority]
    rng.shuffle(remaining)
    return (priority + remaining)[:employee_count]


def _salary_for_grade(grade: str, rng: random.Random) -> Decimal:
    base = {
        "G3": 1800,
        "G4": 2300,
        "G5": 3000,
        "G6": 3800,
        "G7": 5000,
        "G8": 6800,
        "G9": 9000,
    }[grade]
    return Decimal(base + rng.randint(-180, 260)).quantize(Decimal("0.01"))


def _leave_balances_for_employee(*, employee: Employee, year: int, seed: int) -> list[LeaveBalance]:
    annual_total = Decimal("18.00") if employee.grade in {"G3", "G4", "G5"} else Decimal("24.00")
    sick_total = Decimal("10.00")
    unpaid_total = Decimal("30.00")

    employee_id = int(employee.id or 0)
    annual_used = Decimal(str(random.Random(seed + employee_id).randint(0, int(annual_total))))
    sick_used = Decimal(str(random.Random(seed * 2 + employee_id).randint(0, int(sick_total // 2 + 1))))
    unpaid_used = Decimal(str(random.Random(seed * 3 + employee_id).randint(0, 3)))

    return [
        LeaveBalance(
            employee_id=employee_id,
            leave_type="annual",
            year=year,
            days_total=annual_total,
            days_used=annual_used,
        ),
        LeaveBalance(
            employee_id=employee_id,
            leave_type="sick",
            year=year,
            days_total=sick_total,
            days_used=sick_used,
        ),
        LeaveBalance(
            employee_id=employee_id,
            leave_type="unpaid",
            year=year,
            days_total=unpaid_total,
            days_used=unpaid_used,
        ),
    ]


def _leave_requests_for_employee(*, employee: Employee, today: date, seed: int, rng: random.Random) -> list[LeaveRequest]:
    employee_id = int(employee.id or 0)
    approver_id = employee.manager_id
    requests: list[LeaveRequest] = []
    for offset in range(rng.randint(1, 3)):
        leave_type = LEAVE_TYPES[(employee_id + offset) % len(LEAVE_TYPES)]
        start = today - timedelta(days=rng.randint(0, 300))
        duration = rng.randint(1, 7)
        requests.append(
            LeaveRequest(
                employee_id=employee_id,
                start_date=start,
                end_date=start + timedelta(days=duration),
                type=leave_type,
                status=LEAVE_STATUSES[(employee_id + offset) % len(LEAVE_STATUSES)],
                approver_id=approver_id,
            )
        )
    return requests


def generate_synthetic_dataset(
    employee_count: int = 60,
    seed: int = 7,
    *,
    reserved_names: set[str] | None = None,
) -> SyntheticDataset:
    if employee_count < 50 or employee_count > 80:
        raise ValueError("employee_count must stay within the spec range 50-80.")

    rng = random.Random(seed)
    today = date.today()
    employees: list[Employee] = []
    leave_balances: list[LeaveBalance] = []
    leave_requests: list[LeaveRequest] = []
    names = _build_name_sequence(employee_count=employee_count, seed=seed, reserved_names=reserved_names)

    manager_ids_by_department: dict[str, list[int]] = {department: [] for department in DEPARTMENTS}

    for index in range(employee_count):
        department = DEPARTMENTS[index % len(DEPARTMENTS)]
        if index < len(DEPARTMENTS):
            grade = "G8"
        elif index < len(DEPARTMENTS) * 2:
            grade = "G7"
        else:
            grade = rng.choice(GRADES[:-1])

        manager_id = None
        if manager_ids_by_department[department]:
            manager_id = rng.choice(manager_ids_by_department[department])
        elif employees:
            existing_managers = [employee.id for employee in employees if employee.id is not None and employee.grade in {"G8", "G9"}]
            manager_id = rng.choice(existing_managers) if existing_managers else None

        hire_date = today - timedelta(days=rng.randint(120, 3650))
        contract_end_date = None
        if rng.random() < 0.15:
            contract_end_date = today + timedelta(days=rng.randint(30, 540))

        status = "active"
        if rng.random() < 0.08:
            status = "on_leave"
        elif rng.random() < 0.04:
            status = "left"

        employee = Employee(
            full_name=names[index],
            department=department,
            grade=grade,
            manager_id=manager_id,
            hire_date=hire_date,
            contract_end_date=contract_end_date,
            salary=_salary_for_grade(grade, rng),
            status=status,
        )
        employee.id = index + 1
        employees.append(employee)

        if grade in {"G7", "G8", "G9"} and status != "left":
            manager_ids_by_department[department].append(employee.id)

    for employee in employees:
        leave_balances.extend(_leave_balances_for_employee(employee=employee, year=today.year, seed=seed))
        leave_requests.extend(_leave_requests_for_employee(employee=employee, today=today, seed=seed, rng=rng))

    return SyntheticDataset(
        employees=employees,
        leave_balances=leave_balances,
        leave_requests=leave_requests,
    )
