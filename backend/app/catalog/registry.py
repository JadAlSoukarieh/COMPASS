from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogParam:
    name: str
    type: str
    description: str
    required: bool = False
    min_value: int | None = None
    max_value: int | None = None
    allowed_values: tuple[str, ...] = ()
    entity: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    description: str
    params: tuple[CatalogParam, ...]
    required_roles: tuple[str, ...]
    scope: str
    sql: str
    scope_column: str | None = None
    supports_employee_param: bool = False
    formatter_hint: str | None = None

    def prompt_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "params": [
                {
                    "name": param.name,
                    "type": param.type,
                    "required": param.required,
                    "description": param.description,
                    "allowed_values": list(param.allowed_values),
                    "entity": param.entity,
                }
                for param in self.params
            ],
        }


CURRENT_YEAR = date.today().year

CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        id="EMP_LEAVE_BALANCE",
        description="Leave balance by type for a specific employee.",
        params=(
            CatalogParam("employee_id", "int", "Employee id to inspect.", entity="employee"),
            CatalogParam("employee_name", "str", "Optional full employee name to inspect.", entity="employee_name"),
            CatalogParam("department", "str", "Optional department to disambiguate employee name.", entity="department"),
            CatalogParam("grade", "str", "Optional grade to disambiguate employee name.", entity="grade"),
            CatalogParam("leave_type", "str", "Optional leave type filter.", allowed_values=("annual", "sick", "unpaid")),
            CatalogParam("year", "int", "Balance year.", min_value=2024, max_value=CURRENT_YEAR + 1),
        ),
        required_roles=("emp", "mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lb.employee_id,
                e.full_name,
                lb.leave_type,
                lb.year,
                lb.days_total,
                lb.days_used,
                (lb.days_total - lb.days_used) AS days_remaining
            FROM leave_balances lb
            JOIN employees e ON e.id = lb.employee_id
            WHERE {scope_clause}
              AND (CAST(:employee_id AS INTEGER) IS NULL OR lb.employee_id = :employee_id)
              AND (CAST(:leave_type AS TEXT) IS NULL OR lb.leave_type = :leave_type)
              AND lb.year = :year
            ORDER BY e.full_name, lb.leave_type
        """,
        scope_column="lb.employee_id",
        supports_employee_param=True,
        formatter_hint="Summarize remaining leave by type.",
    ),
    CatalogEntry(
        id="EMP_LEAVE_HISTORY",
        description="Recent leave requests and statuses for an employee.",
        params=(
            CatalogParam("employee_id", "int", "Employee id to inspect.", entity="employee"),
            CatalogParam("employee_name", "str", "Optional full employee name to inspect.", entity="employee_name"),
            CatalogParam("department", "str", "Optional department to disambiguate employee name.", entity="department"),
            CatalogParam("grade", "str", "Optional grade to disambiguate employee name.", entity="grade"),
            CatalogParam("status", "str", "Optional leave request status.", allowed_values=("pending", "approved", "rejected")),
            CatalogParam("limit", "int", "Maximum rows to return.", min_value=1, max_value=20),
        ),
        required_roles=("emp", "mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lr.id,
                lr.employee_id,
                e.full_name,
                lr.type,
                lr.status,
                lr.start_date,
                lr.end_date
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            WHERE {scope_clause}
              AND (CAST(:employee_id AS INTEGER) IS NULL OR lr.employee_id = :employee_id)
              AND (CAST(:status AS TEXT) IS NULL OR lr.status = :status)
            ORDER BY lr.start_date DESC, lr.id DESC
            LIMIT :limit
        """,
        scope_column="lr.employee_id",
        supports_employee_param=True,
        formatter_hint="Summarize recent leave history with status and dates.",
    ),
    CatalogEntry(
        id="EMP_TENURE",
        description="Hire date, tenure, and contract end date for an employee.",
        params=(
            CatalogParam("employee_id", "int", "Employee id to inspect.", entity="employee"),
            CatalogParam("employee_name", "str", "Optional full employee name to inspect.", entity="employee_name"),
            CatalogParam("department", "str", "Optional department to disambiguate employee name.", entity="department"),
            CatalogParam("grade", "str", "Optional grade to disambiguate employee name.", entity="grade"),
        ),
        required_roles=("emp", "mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade,
                e.hire_date,
                e.contract_end_date,
                e.status
            FROM employees e
            WHERE {scope_clause}
              AND (CAST(:employee_id AS INTEGER) IS NULL OR e.id = :employee_id)
            ORDER BY e.full_name
        """,
        scope_column="e.id",
        supports_employee_param=True,
        formatter_hint="Explain tenure and contract timing.",
    ),
    CatalogEntry(
        id="EMP_UPCOMING_LEAVE",
        description="Upcoming approved leave for an employee.",
        params=(
            CatalogParam("employee_id", "int", "Employee id to inspect.", entity="employee"),
            CatalogParam("employee_name", "str", "Optional full employee name to inspect.", entity="employee_name"),
            CatalogParam("department", "str", "Optional department to disambiguate employee name.", entity="department"),
            CatalogParam("grade", "str", "Optional grade to disambiguate employee name.", entity="grade"),
            CatalogParam("days_ahead", "int", "Lookahead window in days.", min_value=1, max_value=365),
        ),
        required_roles=("emp", "mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lr.employee_id,
                e.full_name,
                lr.type,
                lr.start_date,
                lr.end_date,
                lr.status
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            WHERE {scope_clause}
              AND (CAST(:employee_id AS INTEGER) IS NULL OR lr.employee_id = :employee_id)
              AND lr.status = 'approved'
              AND lr.start_date >= CURRENT_DATE
              AND lr.start_date <= CURRENT_DATE + CAST(:days_ahead AS INTEGER)
            ORDER BY lr.start_date ASC
        """,
        scope_column="lr.employee_id",
        supports_employee_param=True,
        formatter_hint="Summarize upcoming approved leave.",
    ),
    CatalogEntry(
        id="TEAM_HEADCOUNT_BY_GRADE",
        description="Headcount by grade within the requester scope.",
        params=(),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT e.grade, COUNT(*) AS headcount
            FROM employees e
            WHERE {scope_clause}
            GROUP BY e.grade
            ORDER BY e.grade
        """,
        scope_column="e.id",
        formatter_hint="Summarize headcount by grade.",
    ),
    CatalogEntry(
        id="TEAM_SALARY_SUMMARY",
        description="Salary summary by department and grade within the requester scope.",
        params=(),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.department,
                e.grade,
                COUNT(*) AS employee_count,
                AVG(e.salary) AS avg_salary,
                MIN(e.salary) AS min_salary,
                MAX(e.salary) AS max_salary
            FROM employees e
            WHERE {scope_clause}
            GROUP BY e.department, e.grade
            ORDER BY e.department, e.grade
        """,
        scope_column="e.id",
        formatter_hint="Summarize salary distribution within the visible team.",
    ),
    CatalogEntry(
        id="TEAM_ON_LEAVE_PERIOD",
        description="Employees on leave within the next period.",
        params=(CatalogParam("days_ahead", "int", "Lookahead window in days.", min_value=1, max_value=180),),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lr.employee_id,
                e.full_name,
                lr.type,
                lr.status,
                lr.start_date,
                lr.end_date
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            WHERE {scope_clause}
              AND lr.status IN ('pending', 'approved')
              AND lr.start_date <= CURRENT_DATE + CAST(:days_ahead AS INTEGER)
              AND lr.end_date >= CURRENT_DATE
            ORDER BY lr.start_date ASC
        """,
        scope_column="lr.employee_id",
        formatter_hint="Summarize who is on leave soon.",
    ),
    CatalogEntry(
        id="TEAM_PENDING_MY_APPROVAL",
        description="Pending leave requests awaiting the current manager's approval.",
        params=(),
        required_roles=("mgr", "hr", "superuser"),
        scope="team",
        sql="""
            SELECT
                lr.id,
                lr.employee_id,
                e.full_name,
                lr.type,
                lr.start_date,
                lr.end_date,
                lr.status
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            WHERE {scope_clause}
              AND lr.status = 'pending'
              AND (CAST(:approver_id AS INTEGER) IS NULL OR lr.approver_id = :approver_id)
            ORDER BY lr.start_date ASC
        """,
        scope_column="lr.employee_id",
        formatter_hint="Summarize pending approvals.",
    ),
    CatalogEntry(
        id="TEAM_PROBATION_ENDING",
        description="Employees whose contracts end within the next N days.",
        params=(CatalogParam("days", "int", "Number of days ahead.", min_value=1, max_value=365),),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade,
                e.contract_end_date
            FROM employees e
            WHERE {scope_clause}
              AND e.contract_end_date IS NOT NULL
              AND e.contract_end_date <= CURRENT_DATE + CAST(:days AS INTEGER)
            ORDER BY e.contract_end_date ASC
        """,
        scope_column="e.id",
        formatter_hint="List contracts ending soon.",
    ),
    CatalogEntry(
        id="TEAM_BURNOUT_SIGNAL",
        description="Employees with no approved annual leave in the last N months.",
        params=(CatalogParam("months", "int", "Lookback window in months.", min_value=1, max_value=18),),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade
            FROM employees e
            WHERE {scope_clause}
              AND NOT EXISTS (
                SELECT 1
                FROM leave_requests lr
                WHERE lr.employee_id = e.id
                  AND lr.status = 'approved'
                  AND lr.type = 'annual'
                  AND lr.start_date >= CURRENT_DATE - CAST(:lookback_days AS INTEGER)
              )
            ORDER BY e.full_name
        """,
        scope_column="e.id",
        formatter_hint="Highlight employees with no recent annual leave.",
    ),
    CatalogEntry(
        id="TEAM_CARRYOVER_RISK",
        description="Employees with high unused annual leave balances.",
        params=(
            CatalogParam("min_remaining", "int", "Minimum remaining annual leave days.", min_value=1, max_value=40),
            CatalogParam("year", "int", "Balance year.", min_value=2024, max_value=CURRENT_YEAR + 1),
        ),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lb.employee_id,
                e.full_name,
                lb.year,
                (lb.days_total - lb.days_used) AS days_remaining
            FROM leave_balances lb
            JOIN employees e ON e.id = lb.employee_id
            WHERE {scope_clause}
              AND lb.leave_type = 'annual'
              AND lb.year = :year
              AND (lb.days_total - lb.days_used) >= :min_remaining
            ORDER BY days_remaining DESC, e.full_name
        """,
        scope_column="lb.employee_id",
        formatter_hint="Summarize annual leave carryover risk.",
    ),
    CatalogEntry(
        id="CO_HEADCOUNT_BY_DEPT",
        description="Headcount by department.",
        params=(),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT e.department, COUNT(*) AS headcount
            FROM employees e
            WHERE {scope_clause}
            GROUP BY e.department
            ORDER BY headcount DESC, e.department
        """,
        scope_column="e.id",
        formatter_hint="Summarize department headcount.",
    ),
    CatalogEntry(
        id="VISIBLE_EMPLOYEE_DIRECTORY",
        description="Visible employees filtered by name, department, grade, or status.",
        params=(
            CatalogParam("name_query", "str", "Optional case-insensitive employee-name search fragment."),
            CatalogParam("department", "str", "Optional department filter.", entity="department"),
            CatalogParam("grade", "str", "Optional grade filter.", entity="grade"),
            CatalogParam("status", "str", "Optional employee status filter.", entity="employee_status"),
            CatalogParam("limit", "int", "Maximum rows to return.", min_value=1, max_value=50),
        ),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade,
                e.status,
                e.manager_id,
                m.full_name AS manager_name
            FROM employees e
            LEFT JOIN employees m ON m.id = e.manager_id
            WHERE {scope_clause}
              AND (CAST(:name_query AS TEXT) IS NULL OR LOWER(e.full_name) LIKE '%' || LOWER(:name_query) || '%')
              AND (CAST(:department AS TEXT) IS NULL OR e.department = :department)
              AND (CAST(:grade AS TEXT) IS NULL OR e.grade = :grade)
              AND (CAST(:status AS TEXT) IS NULL OR e.status = :status)
            ORDER BY e.full_name, e.id
            LIMIT :limit
        """,
        scope_column="e.id",
        formatter_hint="List matching employees with ids, department, grade, status, and manager.",
    ),
    CatalogEntry(
        id="CO_SALARY_DISTRIBUTION",
        description="Salary distribution by department and grade.",
        params=(
            CatalogParam("department", "str", "Optional department filter.", entity="department"),
        ),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.department,
                e.grade,
                COUNT(*) AS employee_count,
                AVG(e.salary) AS avg_salary,
                MIN(e.salary) AS min_salary,
                MAX(e.salary) AS max_salary
            FROM employees e
            WHERE {scope_clause}
              AND (CAST(:department AS TEXT) IS NULL OR e.department = :department)
            GROUP BY e.department, e.grade
            ORDER BY e.department, e.grade
        """,
        scope_column="e.id",
        formatter_hint="Summarize salary distribution.",
    ),
    CatalogEntry(
        id="CO_HEADCOUNT_BY_STATUS",
        description="Headcount by employee status, optionally filtered to one department.",
        params=(CatalogParam("department", "str", "Optional department filter.", entity="department"),),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.status,
                COUNT(*) AS headcount
            FROM employees e
            WHERE {scope_clause}
              AND (CAST(:department AS TEXT) IS NULL OR e.department = :department)
            GROUP BY e.status
            ORDER BY headcount DESC, e.status
        """,
        scope_column="e.id",
        formatter_hint="Summarize employee status distribution.",
    ),
    CatalogEntry(
        id="CO_CONTRACTS_EXPIRING",
        description="Contracts expiring within the next N days.",
        params=(CatalogParam("days", "int", "Lookahead window in days.", min_value=1, max_value=365),),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade,
                e.contract_end_date
            FROM employees e
            WHERE {scope_clause}
              AND e.contract_end_date IS NOT NULL
              AND e.contract_end_date <= CURRENT_DATE + CAST(:days AS INTEGER)
            ORDER BY e.contract_end_date ASC
        """,
        scope_column="e.id",
        formatter_hint="List contracts expiring soon.",
    ),
    CatalogEntry(
        id="CO_NEW_HIRES",
        description="Employees hired in the last N days.",
        params=(CatalogParam("days", "int", "Lookback window in days.", min_value=1, max_value=365),),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.id AS employee_id,
                e.full_name,
                e.department,
                e.grade,
                e.hire_date
            FROM employees e
            WHERE {scope_clause}
              AND e.hire_date >= CURRENT_DATE - CAST(:days AS INTEGER)
            ORDER BY e.hire_date DESC
        """,
        scope_column="e.id",
        formatter_hint="Summarize recent hires.",
    ),
    CatalogEntry(
        id="CO_AVG_TENURE_BY_DEPT",
        description="Average tenure by department.",
        params=(),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.department,
                COUNT(*) AS employee_count,
                AVG(CURRENT_DATE - e.hire_date) AS avg_tenure_days
            FROM employees e
            WHERE {scope_clause}
            GROUP BY e.department
            ORDER BY avg_tenure_days DESC, e.department
        """,
        scope_column="e.id",
        formatter_hint="Summarize average tenure by department.",
    ),
    CatalogEntry(
        id="CO_LEAVE_UTILIZATION_BY_DEPT",
        description="Leave utilization by department for a given year.",
        params=(CatalogParam("year", "int", "Balance year.", min_value=2024, max_value=CURRENT_YEAR + 1),),
        required_roles=("hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                e.department,
                SUM(lb.days_total) AS days_total,
                SUM(lb.days_used) AS days_used
            FROM leave_balances lb
            JOIN employees e ON e.id = lb.employee_id
            WHERE {scope_clause}
              AND lb.year = :year
              AND lb.leave_type = 'annual'
            GROUP BY e.department
            ORDER BY e.department
        """,
        scope_column="lb.employee_id",
        formatter_hint="Summarize annual leave utilization by department.",
    ),
    CatalogEntry(
        id="SIG_APPROVAL_BOTTLENECK",
        description="Approvers with the largest pending approval workload.",
        params=(),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                a.id AS approver_id,
                a.full_name AS approver_name,
                COUNT(*) AS pending_count
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            JOIN employees a ON a.id = lr.approver_id
            WHERE {scope_clause}
              AND lr.status = 'pending'
              AND lr.approver_id IS NOT NULL
            GROUP BY a.id, a.full_name
            ORDER BY pending_count DESC, approver_name
        """,
        scope_column="lr.employee_id",
        formatter_hint="Identify approval bottlenecks.",
    ),
    CatalogEntry(
        id="SIG_OVERDUE_APPROVALS",
        description="Pending leave approvals older than N days.",
        params=(CatalogParam("days", "int", "Minimum age in days.", min_value=1, max_value=90),),
        required_roles=("mgr", "hr", "superuser"),
        scope="company",
        sql="""
            SELECT
                lr.id,
                e.full_name,
                lr.type,
                lr.start_date,
                lr.end_date,
                lr.status
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
            WHERE {scope_clause}
              AND lr.status = 'pending'
              AND lr.start_date <= CURRENT_DATE - CAST(:days AS INTEGER)
            ORDER BY lr.start_date ASC
        """,
        scope_column="lr.employee_id",
        formatter_hint="List overdue pending approvals.",
    ),
)

CATALOG_BY_ID = {entry.id: entry for entry in CATALOG}


def catalog_prompt_entries() -> list[dict[str, Any]]:
    return [entry.prompt_payload() for entry in CATALOG]
