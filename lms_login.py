"""KNU LMS 로그인 세션 저장.

headless 계정 검증 또는 사용자가 직접 로그인한 브라우저 세션으로
Playwright storage_state에 쿠키를 저장한다.
앱 경로에서는 비밀번호를 stdin으로만 받고 저장하지 않는다.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
from urllib.parse import urljoin

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

DEFAULT_LMS_URL = "https://knulms.kongju.ac.kr"
DEFAULT_PORTAL_URL = "https://portal.kongju.ac.kr/index.jsp"
DEFAULT_SSO_LOGIN_URL = (
    "https://kncu.kongju.ac.kr/xn-sso/login.php"
    "?auto_login=&sso_only=&cvs_lgn=true&return_url="
    "https%3A%2F%2Fkncu.kongju.ac.kr%2Fxn-sso%2Fgw-cb.php%3Ffrom%3Dweb_redirect%26"
    "login_type%3Dstandalone%26return_url%3Dhttps%253A%252F%252Fknulms.kongju.ac.kr%252Flearningx%252Flogin"
)
DEFAULT_SSO_CALLBACK_URL = (
    "https://kncu.kongju.ac.kr/xn-sso/gw-cb.php"
    "?from=web_redirect&login_type=standalone&return_url="
    "https%3A%2F%2Fknulms.kongju.ac.kr%2Flearningx%2Flogin"
)
DEFAULT_STATE_PATH = ".secrets/lms_storage_state.json"
DEFAULT_DEBUG_DIR = ".secrets/lms_login_debug"


def _canvas_api_url(lms_url: str, path: str) -> str:
    return urljoin(lms_url.rstrip("/") + "/", path.lstrip("/"))


def _is_canvas_session_ready(context, lms_url: str) -> bool:
    response = context.request.get(_canvas_api_url(lms_url, "/api/v1/users/self"))
    return response.ok


def _can_launch_headed_browser() -> bool:
    if sys.platform != "linux":
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


def _fill_first_available(page: Page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(f"{selector}:visible")
        if locator.count() == 0:
            continue
        target = locator.first
        try:
            target.fill(value, timeout=3000)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def _submit_login_form(page: Page) -> None:
    if page.locator("form[name='form1']").count() > 0:
        try:
            page.evaluate(
                """(action) => {
                    const form = document.forms["form1"];
                    form.action = action;
                    form.target = "_top";
                    if (form.requestSubmit) {
                        form.requestSubmit();
                    } else {
                        form.submit();
                    }
                }""",
                DEFAULT_SSO_CALLBACK_URL,
            )
            page.wait_for_url(lambda url: "login.php" not in url, timeout=3000)
            return
        except Exception:
            login_link = page.locator("a[href*='OnLogon']:visible")
            if login_link.count() > 0:
                login_link.first.click(timeout=3000)
                return

    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "a[href*='OnLogon']",
        "button:has-text('로그인')",
        "a:has-text('로그인')",
        "button:has-text('Login')",
    ]
    for selector in submit_selectors:
        locator = page.locator(f"{selector}:visible")
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            continue
    page.keyboard.press("Enter")


def _save_debug_artifacts(page: Page, debug_dir: Path, reason: str) -> Path:
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time()))
    base = debug_dir / f"{stamp}_{reason}"
    try:
        form_debug = page.evaluate(
            """() => {
                const form = document.forms["form1"];
                if (!form) return {};
                return {
                    action: form.action,
                    target: form.target,
                    idValueLength: form.login_user_id ? form.login_user_id.value.length : null,
                    pwValueLength: form.login_user_password ? form.login_user_password.value.length : null,
                    bodyText: document.body ? document.body.innerText.slice(0, 1000) : ""
                };
            }"""
        )
        (base.with_suffix(".url.txt")).write_text(
            f"title={page.title()}\nurl={page.url}\nform={form_debug}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    try:
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except Exception:
        pass
    return base


def _wait_for_canvas_session(context, page: Page, lms_url: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    visited_lms = False
    while time.monotonic() < deadline:
        if _is_canvas_session_ready(context, lms_url):
            return True

        # 포털/SSO 로그인 후 포털 메인에 머무르면 LMS에 한 번 진입해 Canvas 쿠키를 만든다.
        # 단, kncu SSO login.php/gw-cb.php 리다이렉트 중에는 흐름을 끊지 않는다.
        if (
            not visited_lms
            and "portal.kongju.ac.kr" in page.url
            and "kncu.kongju.ac.kr" not in page.url
        ):
            try:
                page.goto(lms_url, wait_until="domcontentloaded", timeout=15000)
                visited_lms = True
            except PlaywrightTimeoutError:
                pass

        time.sleep(1)
    return False


def _login_with_credentials(
    *,
    url: str,
    lms_url: str,
    state_path: Path,
    username: str,
    password: str,
    timeout: int,
    debug_dir: Path,
) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("input[type='password']", timeout=15000)
        except PlaywrightTimeoutError:
            pass

        username_filled = _fill_first_available(
            page,
            [
                "input[name='login_id']",
                "input[name='login_user_id']",
                "input[name='userId']",
                "input[name='userID']",
                "input[name='username']",
                "input[name='user_id']",
                "input[name='uid']",
                "input[name='id']",
                "input[id='login_id']",
                "input[id='login_user_id']",
                "input[id='userId']",
                "input[id='userID']",
                "input[id='username']",
                "input[id='user_id']",
                "input[id='uid']",
                "input[id='id']",
                "input[type='email']",
                "input[type='text']",
            ],
            username,
        )
        password_filled = _fill_first_available(
            page,
            [
                "input[name='password']",
                "input[name='login_user_password']",
                "input[name='passwd']",
                "input[name='userPw']",
                "input[name='userPW']",
                "input[name='pw']",
                "input[id='password']",
                "input[id='login_user_password']",
                "input[id='passwd']",
                "input[id='userPw']",
                "input[id='userPW']",
                "input[id='pw']",
                "input[type='password']",
            ],
            password,
        )
        if not username_filled or not password_filled:
            base = _save_debug_artifacts(page, debug_dir, "missing_inputs")
            browser.close()
            raise RuntimeError(
                "로그인 입력칸을 찾지 못했습니다. SSO 화면 구조가 예상과 다릅니다. "
                f"디버그 파일: {base}"
            )

        _submit_login_form(page)
        try:
            page.wait_for_url(lambda url: "login.php" not in url, timeout=15000)
        except PlaywrightTimeoutError:
            pass
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        if _wait_for_canvas_session(context, page, lms_url, timeout):
            context.storage_state(path=str(state_path))
            browser.close()
            return

        base = _save_debug_artifacts(page, debug_dir, "session_not_ready")
        browser.close()
        raise RuntimeError(
            "LMS 로그인이 확인되지 않았습니다. 계정 정보, 추가 인증, 또는 SSO 흐름을 확인해 주세요. "
            f"디버그 파일: {base}"
        )


def login_with_credentials(
    username: str,
    password: str,
    *,
    url: str = DEFAULT_LMS_URL,
    lms_url: str = DEFAULT_LMS_URL,
    state: str = DEFAULT_STATE_PATH,
    timeout: int = 60,
    debug_dir: str = DEFAULT_DEBUG_DIR,
) -> None:
    """앱에서 받은 계정정보로 headless 로그인 검증 후 세션만 저장한다."""
    state_path = Path(state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    _login_with_credentials(
        url=url,
        lms_url=lms_url,
        state_path=state_path,
        username=username,
        password=password,
        timeout=timeout,
        debug_dir=Path(debug_dir),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="KNU LMS 로그인 세션 저장")
    parser.add_argument("--url", default=DEFAULT_SSO_LOGIN_URL, help="로그인을 시작할 URL")
    parser.add_argument("--lms-url", default=DEFAULT_LMS_URL, help="Canvas 세션을 확인할 LMS URL")
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
    parser.add_argument("--username", help="headless 로그인 검증용 아이디")
    parser.add_argument("--debug-dir", default=DEFAULT_DEBUG_DIR)
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="비밀번호를 stdin 첫 줄에서 읽어 headless 로그인 검증",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if args.username or args.password_stdin:
        if not args.username or not args.password_stdin:
            raise SystemExit("--username과 --password-stdin은 함께 사용해야 합니다.")
        password = sys.stdin.readline().rstrip("\n")
        try:
            login_with_credentials(
                args.username,
                password,
                url=args.url,
                lms_url=args.lms_url,
                state=args.state,
                timeout=args.timeout,
                debug_dir=args.debug_dir,
            )
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"세션 저장 완료: {state_path}")
        return 0

    print("브라우저가 열리면 LMS에 직접 로그인하세요.")
    if args.auto:
        print("로그인이 확인되면 세션을 자동 저장하고 창을 닫습니다.")
    else:
        print("로그인이 끝나고 LMS 첫 화면이 보이면 터미널에서 Enter를 누르면 됩니다.")
    print("아이디/비밀번호는 이 스크립트가 읽거나 저장하지 않습니다.")

    if not _can_launch_headed_browser():
        raise SystemExit(
            "GUI 브라우저를 열 수 없습니다. Linux/Docker 환경에 DISPLAY가 없습니다.\n"
            "프로젝트가 bind mount되어 있다면 호스트 macOS 터미널에서 실행하세요:\n"
            "  python3 lms_login.py --auto\n"
            "그러면 생성된 .secrets/lms_storage_state.json을 컨테이너 앱이 그대로 사용합니다."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded")

        if args.auto:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                if _is_canvas_session_ready(context, args.lms_url):
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
