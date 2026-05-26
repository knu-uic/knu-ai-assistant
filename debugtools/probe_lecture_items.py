"""Canvas modules API의 ExternalTool item 완료 신호 진단 스크립트.

KNU LMS가 '완료' 가 아니라 '출석' 으로 처리하는지 확인하기 위한 read-only 도구.
lms_sync.py 와 동일한 storage_state / Canvas 토큰을 사용해 활성 과목의
modules+items 를 가져와서 ExternalTool item 의 모든 관련 필드를 dump.

사용법:
  python3 debugtools/probe_lecture_items.py                  # 활성 과목 중 앞 1개
  python3 debugtools/probe_lecture_items.py --max-courses 3  # 앞 3개
  python3 debugtools/probe_lecture_items.py --course-id 1234 # 특정 과목 1개

결과는 stdout 요약 + crawl_result/lecture_probe.json 에 raw JSON 저장.
완료/시청한 영상이 어떤 필드에서 다른지 비교해서 PR #29 의 필터 조건 결정에 사용.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lms_sync import (  # noqa: E402
    DEFAULT_LMS_URL,
    DEFAULT_STATE_PATH,
    _course_map,
    _get_json_doseq,
    _request_context,
)


def _summarize_item(item: dict) -> dict:
    """진단에 필요한 필드만 추려서 요약."""
    return {
        "id": item.get("id"),
        "type": item.get("type"),
        "title": item.get("title"),
        "html_url": item.get("html_url"),
        "url": item.get("url"),
        "external_url": item.get("external_url"),
        "published": item.get("published"),
        "indent": item.get("indent"),
        "completion_requirement": item.get("completion_requirement"),
        "content_details": item.get("content_details"),
    }


def probe(
    base_url: str,
    state_path: Path,
    course_id_filter: int | None,
    max_courses: int,
    out_path: Path,
) -> None:
    with sync_playwright() as p:
        request = _request_context(p, base_url, state_path)
        courses = _course_map(request)
        if not courses:
            print("활성 과목이 없습니다. lms_login.py 로 다시 로그인하거나 토큰을 확인하세요.")
            return

        if course_id_filter is not None:
            courses = {cid: name for cid, name in courses.items() if cid == course_id_filter}
            if not courses:
                print(f"course_id={course_id_filter} 가 활성 과목 목록에 없습니다.")
                return
        else:
            courses = dict(list(courses.items())[:max_courses])

        all_raw: list[dict] = []

        for course_id, course_name in courses.items():
            print(f"\n=== course {course_id}: {course_name} ===")

            # 1) 기본 호출 (현재 lms_sync 와 동일)
            try:
                modules_default = _get_json_doseq(
                    request,
                    f"/api/v1/courses/{course_id}/modules",
                    {
                        "include[]": ["items", "content_details"],
                        "per_page": 100,
                    },
                )
            except RuntimeError as exc:
                print(f"  [default] modules API 실패: {exc}")
                modules_default = None

            # 2) student_id=self 추가
            try:
                modules_self = _get_json_doseq(
                    request,
                    f"/api/v1/courses/{course_id}/modules",
                    {
                        "include[]": ["items", "content_details"],
                        "student_id": "self",
                        "per_page": 100,
                    },
                )
            except RuntimeError as exc:
                print(f"  [student_id=self] modules API 실패: {exc}")
                modules_self = None

            # 3) current_user_progressions include 시도
            try:
                modules_progress = _get_json_doseq(
                    request,
                    f"/api/v1/courses/{course_id}/modules",
                    {
                        "include[]": [
                            "items",
                            "content_details",
                            "current_user_progressions",
                        ],
                        "per_page": 100,
                    },
                )
            except RuntimeError as exc:
                print(f"  [current_user_progressions] modules API 실패: {exc}")
                modules_progress = None

            picked = modules_self or modules_default or modules_progress or []
            if not isinstance(picked, list):
                print("  modules 응답이 list 가 아님. skip.")
                continue

            ext_items: list[dict] = []
            for module in picked:
                module_id = module.get("id")
                module_name = module.get("name")
                module_state = module.get("state")
                for item in module.get("items") or []:
                    if item.get("type") != "ExternalTool":
                        continue
                    summary = _summarize_item(item)
                    summary["_module_id"] = module_id
                    summary["_module_name"] = module_name
                    summary["_module_state"] = module_state
                    ext_items.append(summary)

            print(f"  ExternalTool item: {len(ext_items)}개")
            for it in ext_items:
                cr = it["completion_requirement"]
                cr_str = (
                    f"type={cr.get('type')!r} completed={cr.get('completed')!r}"
                    if isinstance(cr, dict)
                    else str(cr)
                )
                print(
                    f"   - id={it['id']} module={it['_module_name']!r} "
                    f"state={it['_module_state']!r} "
                    f"title={it['title']!r} cr=({cr_str})"
                )

            all_raw.append({
                "course_id": course_id,
                "course_name": course_name,
                "modules_default": modules_default,
                "modules_student_self": modules_self,
                "modules_current_user_progressions": modules_progress,
            })

        request.dispose()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(all_raw, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nraw JSON 저장: {out_path}")
    print("이 파일을 공유하거나 ExternalTool item 중 본인이 시청 완료한 영상의 cr 값을 알려주세요.")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Canvas modules ExternalTool item 진단")
    parser.add_argument("--url", default=os.getenv("KNU_LMS_URL", DEFAULT_LMS_URL))
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--course-id", type=int, default=None, help="특정 course_id 만 조회")
    parser.add_argument("--max-courses", type=int, default=1, help="course-id 미지정 시 앞에서 N개")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "crawl_result" / "lecture_probe.json"),
        help="raw JSON 저장 경로",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists() and not (os.getenv("CANVAS_ACCESS_TOKEN") or os.getenv("KNU_LMS_TOKEN")):
        raise SystemExit(
            "저장된 LMS 세션이나 Canvas 토큰이 없습니다. 먼저 `python3 lms_login.py` 로 로그인하세요."
        )

    probe(
        base_url=args.url,
        state_path=state_path,
        course_id_filter=args.course_id,
        max_courses=args.max_courses,
        out_path=Path(args.out),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
