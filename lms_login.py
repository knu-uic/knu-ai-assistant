"""KNU LMS 로그인 세션 저장.

사용자가 열린 브라우저에서 직접 로그인하면 Playwright storage_state에 쿠키를 저장한다.
비밀번호를 스크립트 인자나 환경변수로 받지 않는다.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

DEFAULT_LMS_URL = "https://knulms.kongju.ac.kr"
DEFAULT_STATE_PATH = ".secrets/lms_storage_state.json"


def _is_canvas_session_ready(context, lms_url: str) -> bool:
    response = context.request.get(urljoin(lms_url.rstrip("/") + "/", "/api/v1/users/self"))
    return response.ok


def main() -> int:
    parser = argparse.ArgumentParser(description="KNU LMS 로그인 세션 저장")
    parser.add_argument("--url", default=DEFAULT_LMS_URL, help="LMS URL")
    parser.add_argument(
        "--state",
        default=DEFAULT_STATE_PATH,
        help="저장할 Playwright storage_state JSON 경로",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Enter 입력 없이 Canvas API 로그인 성공을 감지하면 자동 저장",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="--auto 모드에서 로그인 완료를 기다릴 초",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="--auto 모드에서 로그인 상태 확인 주기",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    print("브라우저가 열리면 LMS에 직접 로그인하세요.")
    if args.auto:
        print("로그인이 확인되면 세션을 자동 저장하고 창을 닫습니다.")
    else:
        print("로그인이 끝나고 LMS 첫 화면이 보이면 터미널에서 Enter를 누르면 됩니다.")
    print("아이디/비밀번호는 이 스크립트가 읽거나 저장하지 않습니다.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded")

        if args.auto:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                if _is_canvas_session_ready(context, args.url):
                    break
                time.sleep(args.poll_interval)
            else:
                browser.close()
                raise SystemExit("제한 시간 안에 LMS 로그인이 확인되지 않았습니다.")
        else:
            input("로그인 완료 후 Enter를 누르세요: ")

        context.storage_state(path=str(state_path))
        browser.close()

    print(f"세션 저장 완료: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
