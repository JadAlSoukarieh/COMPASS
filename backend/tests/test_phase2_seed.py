from __future__ import annotations

from collections import Counter

from data.seed.synthetic_data import generate_synthetic_dataset


def test_generate_synthetic_dataset_size_and_relationships() -> None:
    dataset = generate_synthetic_dataset(employee_count=60, seed=11)

    assert len(dataset.employees) == 60
    assert len(dataset.leave_balances) == 180
    assert len(dataset.leave_requests) >= 60

    employee_ids = {employee.id for employee in dataset.employees}
    assert len(employee_ids) == 60
    assert len({employee.full_name for employee in dataset.employees}) == 60

    for employee in dataset.employees:
        if employee.manager_id is not None:
            assert employee.manager_id in employee_ids
            assert employee.manager_id != employee.id


def test_generate_synthetic_dataset_has_hierarchy_and_leave_coverage() -> None:
    dataset = generate_synthetic_dataset(employee_count=72, seed=13)

    by_department = Counter(employee.department for employee in dataset.employees)
    assert len(by_department) >= 5
    assert all(count >= 2 for count in by_department.values())

    manager_ids = {employee.id for employee in dataset.employees if employee.grade in {"G7", "G8", "G9"}}
    direct_reports = [employee for employee in dataset.employees if employee.manager_id is not None]
    assert direct_reports
    assert any(employee.manager_id in manager_ids for employee in direct_reports)

    balances_by_employee = Counter(balance.employee_id for balance in dataset.leave_balances)
    assert all(count == 3 for count in balances_by_employee.values())


def test_generate_synthetic_dataset_respects_reserved_names() -> None:
    dataset = generate_synthetic_dataset(employee_count=60, seed=7, reserved_names={"Hana Rahal", "Mazen Haddad", "Lina Nassar"})

    names = {employee.full_name for employee in dataset.employees}
    assert "Hana Rahal" not in names
    assert "Mazen Haddad" not in names
    assert "Lina Nassar" not in names
    assert "Jad Karam" in names
