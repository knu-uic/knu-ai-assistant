from __future__ import annotations

import json

import psycopg

from db.schema import DB_URL


def ensure_users_schema():
    with psycopg.connect(DB_URL) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                student_id VARCHAR(20) PRIMARY KEY,
                major VARCHAR(50),
                name VARCHAR(50),
                year INT,
                interests TEXT,
                courses TEXT
            );
        """)
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS year INT;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS favorite_courses TEXT;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS graduation_credits JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS timetable JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS grade_distribution_json JSONB;")
        conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cumulative_grades_json JSONB;")
        conn.commit()


def get_user(student_id: str) -> dict | None:
    with psycopg.connect(DB_URL) as conn:
        cur = conn.execute(
            "SELECT student_id, name, major, year, interests, favorite_courses, graduation_credits, timetable, grade_distribution_json, cumulative_grades_json FROM users WHERE student_id = %s;",
            (student_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    sid, name, major, year, interests, favorite_courses, graduation_credits, timetable, grade_distribution, cumulative_grades = row
    if isinstance(graduation_credits, str):
        try:
            graduation_credits = json.loads(graduation_credits)
        except Exception:
            graduation_credits = None
    if isinstance(timetable, str):
        try:
            timetable = json.loads(timetable)
        except Exception:
            timetable = None
    if isinstance(grade_distribution, str):
        try:
            grade_distribution = json.loads(grade_distribution)
        except Exception:
            grade_distribution = None
    if isinstance(cumulative_grades, str):
        try:
            cumulative_grades = json.loads(cumulative_grades)
        except Exception:
            cumulative_grades = None
    return {
        "student_id": sid,
        "name": name,
        "major": major,
        "year": year,
        "interests": [s.strip() for s in (interests or "").split(",") if s.strip()],
        "favorite_courses": [s.strip() for s in (favorite_courses or "").split(",") if s.strip()],
        "graduation_credits": graduation_credits,
        "timetable": timetable,
        "grade_distribution": grade_distribution,
        "cumulative_grades": cumulative_grades,
    }


def upsert_user(
    student_id: str,
    name: str,
    major: str,
    year: int | None,
    interests: list[str] | None = None,
    favorite_courses: list[str] | None = None,
    graduation_credits: dict | None = None,
    timetable: list | None = None,
    grade_distribution: dict | None = None,
    cumulative_grades: dict | None = None,
):
    interests_csv = ",".join(interests) if interests is not None else None
    favorites_csv = ",".join(favorite_courses) if favorite_courses is not None else None
    credits_json = json.dumps(graduation_credits, ensure_ascii=False) if graduation_credits is not None else None
    timetable_json = json.dumps(timetable, ensure_ascii=False) if timetable is not None else None
    grade_distribution_json = json.dumps(grade_distribution, ensure_ascii=False) if grade_distribution is not None else None
    cumulative_grades_json = json.dumps(cumulative_grades, ensure_ascii=False) if cumulative_grades is not None else None
    with psycopg.connect(DB_URL) as conn:
        conn.execute("""
            INSERT INTO users (student_id, name, major, year, interests, favorite_courses, graduation_credits, timetable, grade_distribution_json, cumulative_grades_json)
            VALUES (%s, %s, %s, %s, COALESCE(%s, ''), COALESCE(%s, ''), %s, %s, %s, %s)
            ON CONFLICT (student_id) DO UPDATE SET
                name = EXCLUDED.name,
                major = EXCLUDED.major,
                year = EXCLUDED.year,
                interests = CASE WHEN EXCLUDED.interests IS NOT NULL AND EXCLUDED.interests <> '' THEN EXCLUDED.interests ELSE users.interests END,
                favorite_courses = CASE WHEN EXCLUDED.favorite_courses IS NOT NULL AND EXCLUDED.favorite_courses <> '' THEN EXCLUDED.favorite_courses ELSE users.favorite_courses END,
                graduation_credits = COALESCE(EXCLUDED.graduation_credits, users.graduation_credits),
                timetable = COALESCE(EXCLUDED.timetable, users.timetable),
                grade_distribution_json = COALESCE(EXCLUDED.grade_distribution_json, users.grade_distribution_json),
                cumulative_grades_json = COALESCE(EXCLUDED.cumulative_grades_json, users.cumulative_grades_json);
        """, (student_id, name, major, year, interests_csv, favorites_csv, credits_json, timetable_json, grade_distribution_json, cumulative_grades_json))
        conn.commit()


def set_favorite_courses(student_id: str, courses: list[str]) -> None:
    favorites_csv = ",".join(courses or [])
    with psycopg.connect(DB_URL) as conn:
        conn.execute(
            "UPDATE users SET favorite_courses = %s WHERE student_id = %s;",
            (favorites_csv, student_id),
        )
        conn.commit()


__all__ = ["ensure_users_schema", "get_user", "upsert_user", "set_favorite_courses"]
