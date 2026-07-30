"""Data-only adapters consumed by the Codmes KNU plugin.

These endpoints contain no Codmes presentation, component, icon, search, or
filter definitions. The plugin package owns that UI contract.
"""

from functools import partial

import anyio
from fastapi import APIRouter, Depends

from api.deps import portal_student_id, require_user
from db.accounts import get_account
from db.users import get_user

router = APIRouter()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "예" if value else "아니요"
    return str(value)


async def _linked_student_id(username: str) -> str | None:
    if student_id := portal_student_id(username):
        return student_id
    account = await anyio.to_thread.run_sync(partial(get_account, username))
    return account.get("student_id") if account else None


def _graduation_rows(value: dict, path: tuple[str, ...] = ()) -> list[list[str]]:
    rows = []
    for key, child in value.items():
        child_path = (*path, str(key))
        if not isinstance(child, dict):
            continue
        if "기준" in child or "취득" in child:
            standard = _text(child.get("기준"))
            taken = _text(child.get("취득"))
            try:
                deficit = max(0, float(standard or 0) - float(taken or 0))
                remaining = str(int(deficit)) if deficit.is_integer() else f"{deficit:g}"
            except (TypeError, ValueError):
                remaining = ""
            rows.append([" › ".join(child_path), standard, taken, remaining or "-"])
        else:
            rows.extend(_graduation_rows(child, child_path))
    return rows


def _grid_data(prefix: str, title: str, value: dict) -> dict:
    summaries = []
    summary = value.get("summary") if isinstance(value, dict) else None
    if summary:
        summaries.append({
            "id": f"{prefix}-summary",
            "title": f"{title} 요약",
            "fields": [
                {
                    "id": f"{prefix}-summary-{index}",
                    "label": _text(row[0]) if row else "",
                    "value": _text(row[1]) if len(row) > 1 else "",
                }
                for index, row in enumerate(summary)
            ],
        })
    tables = []
    grids = value.get("grids", {}) if isinstance(value, dict) else {}
    for index, (grid_id, grid) in enumerate(grids.items()):
        columns = [_text(item) for item in (grid.get("columns") or [])]
        width = len(columns)
        rows = [
            [_text(item) for item in list(row)[:width]]
            + [""] * max(0, width - len(row))
            for row in (grid.get("rows") or [])
        ]
        tables.append({
            "id": f"{prefix}-{grid_id}-{index}",
            "title": grid.get("title") or title,
            "columns": columns,
            "rows": rows,
        })
    return {"summaries": summaries, "tables": tables}


@router.get("/codmes/data/portal")
async def portal_plugin_data(username: str = Depends(require_user)) -> dict:
    student_id = await _linked_student_id(username)
    user = (
        await anyio.to_thread.run_sync(partial(get_user, student_id))
        if student_id else None
    ) or {}

    timetable = None
    timetable_value = user.get("timetable") or []
    if timetable_value and timetable_value[0].get("rows"):
        all_rows = timetable_value[0]["rows"]
        timetable = {
            "columns": [_text(item) for item in all_rows[0]],
            "rows": [
                [_text(item) for item in row]
                for row in all_rows[1:]
                if any(_text(cell).strip() for cell in row[1:])
            ],
        }

    graduation = None
    if user.get("graduation_credits"):
        graduation = {
            "columns": ["영역", "기준", "취득", "부족"],
            "rows": _graduation_rows(user["graduation_credits"]),
        }

    return {
        "profile": {
            "student_id": student_id,
            "name": user.get("name"),
            "major": user.get("major"),
            "year": user.get("year"),
        },
        "timetable": timetable,
        "graduation": graduation,
        "grade_distribution": _grid_data(
            "grade-distribution",
            "나의 성적분포",
            user.get("grade_distribution") or {},
        ),
        "cumulative_grades": _grid_data(
            "cumulative-grades",
            "누적 성적",
            user.get("cumulative_grades") or {},
        ),
    }
