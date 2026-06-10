from __future__ import annotations

import json

from db.pool import sync_pool


def upsert_lms_course(student_id: str, course_id: int, course_name: str) -> None:
    with sync_pool.connection() as conn:
        conn.execute("""
            INSERT INTO lms_courses (student_id, course_id, course_name, synced_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (student_id, course_id) DO UPDATE SET
                course_name = EXCLUDED.course_name,
                synced_at = now();
        """, (student_id, course_id, course_name))
        conn.commit()


def get_lms_courses(student_id: str) -> list[dict]:
    with sync_pool.connection() as conn:
        rows = conn.execute(
            "SELECT course_id, course_name FROM lms_courses WHERE student_id = %s ORDER BY course_name ASC;",
            (student_id,),
        ).fetchall()
    return [{"course_id": r[0], "course_name": r[1]} for r in rows]


def delete_canvas_lecture_tasks(student_id: str) -> int:
    with sync_pool.connection() as conn:
        cur = conn.execute(
            "DELETE FROM lms_tasks WHERE student_id = %s AND task_type = 'lecture' AND source = 'canvas';",
            (student_id,),
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted


def delete_canvas_notice_tasks(student_id: str) -> int:
    with sync_pool.connection() as conn:
        cur = conn.execute(
            "DELETE FROM lms_tasks WHERE student_id = %s AND task_type = 'notice' AND source = 'canvas';",
            (student_id,),
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted


def get_lms_tasks(student_id: str, include_done: bool = False) -> list[dict]:
    done_clause = "" if include_done else "AND is_done = false"
    query = f"""
        SELECT id, task_type, title, course_name, due_date, progress, url, is_done
        FROM lms_tasks
        WHERE student_id = %s
          {done_clause}
        ORDER BY
          is_done ASC,
          due_date ASC NULLS LAST,
          created_at DESC;
    """
    with sync_pool.connection() as conn:
        rows = conn.execute(query, (student_id,)).fetchall()

    return [
        {
            "id": row[0],
            "task_type": row[1],
            "title": row[2],
            "course_name": row[3],
            "due_date": row[4],
            "progress": row[5],
            "url": row[6],
            "is_done": row[7],
        }
        for row in rows
    ]


def upsert_lms_task(
    student_id: str,
    task_type: str,
    title: str,
    source: str,
    external_id: str,
    course_name: str | None = None,
    due_date=None,
    progress: int | None = None,
    url: str | None = None,
    is_done: bool = False,
    raw: dict | None = None,
) -> int:
    raw_json = json.dumps(raw or {}, ensure_ascii=False)
    with sync_pool.connection() as conn:
        cur = conn.execute("""
            INSERT INTO lms_tasks
                (
                    student_id, task_type, title, course_name, due_date, progress,
                    url, is_done, source, external_id, synced_at, raw
                )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
            ON CONFLICT (student_id, source, external_id)
            WHERE external_id IS NOT NULL
            DO UPDATE SET
                task_type = EXCLUDED.task_type,
                title = EXCLUDED.title,
                course_name = EXCLUDED.course_name,
                due_date = EXCLUDED.due_date,
                progress = EXCLUDED.progress,
                url = EXCLUDED.url,
                is_done = EXCLUDED.is_done,
                synced_at = now(),
                raw = EXCLUDED.raw,
                updated_at = now()
            RETURNING id;
        """, (
            student_id,
            task_type,
            title,
            course_name,
            due_date,
            progress,
            url,
            is_done,
            source,
            external_id,
            raw_json,
        ))
        row = cur.fetchone()
        conn.commit()
    assert row is not None
    return row[0]


def set_lms_task_done(task_id: int, student_id: str, is_done: bool) -> None:
    with sync_pool.connection() as conn:
        conn.execute("""
            UPDATE lms_tasks
            SET is_done = %s,
                updated_at = now()
            WHERE id = %s
              AND student_id = %s;
        """, (is_done, task_id, student_id))
        conn.commit()


def delete_lms_task(task_id: int, student_id: str) -> None:
    with sync_pool.connection() as conn:
        conn.execute(
            "DELETE FROM lms_tasks WHERE id = %s AND student_id = %s;",
            (task_id, student_id),
        )
        conn.commit()


__all__ = [
    "upsert_lms_course",
    "get_lms_courses",
    "delete_canvas_lecture_tasks",
    "delete_canvas_notice_tasks",
    "get_lms_tasks",
    "upsert_lms_task",
    "set_lms_task_done",
    "delete_lms_task",
]
