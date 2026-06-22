from __future__ import annotations

import json
from typing import Any

from backend.app.llm.client import chat_json


def phrase_catalog_answer(
    question: str,
    *,
    catalog_id: str,
    formatter_hint: str | None,
    rows: list[dict[str, Any]],
) -> str:
    if not rows:
        return "No matching rows were found for that question."

    try:
        payload = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You answer an internal HR data question using only the provided structured rows. "
                        "Return JSON only with key answer_markdown. "
                        "Do not invent rows, do not mention SQL, and keep the answer concise."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "question": question,
                            "catalog_id": catalog_id,
                            "formatter_hint": formatter_hint,
                            "rows": rows,
                        }
                    ),
                },
            ],
            temperature=0.0,
        )
        answer_markdown = str(payload.get("answer_markdown") or "").strip()
        if answer_markdown:
            return answer_markdown
    except Exception:
        pass
    return _fallback_answer(catalog_id, rows)


def _fallback_answer(catalog_id: str, rows: list[dict[str, Any]]) -> str:
    if catalog_id == "EMP_LEAVE_BALANCE":
        primary = rows[0]
        employee_label = str(primary.get("full_name") or f"Employee {primary.get('employee_id')}")
        leave_type = str(primary.get("leave_type") or "leave")
        remaining = primary.get("days_remaining")
        year = primary.get("year")
        if remaining is not None:
            return f"{employee_label} has {remaining:g} {leave_type} leave days remaining for {year}."

    sample_rows = rows[:5]
    lines = [f"Results from `{catalog_id}`:"]
    for row in sample_rows:
        parts = [f"{key}={value}" for key, value in row.items()]
        lines.append(f"- {', '.join(parts)}")
    if len(rows) > len(sample_rows):
        lines.append(f"- {len(rows) - len(sample_rows)} more row(s) omitted.")
    return "\n".join(lines)
