"""가입 인증 메일 발송. MAIL_PROVIDER env로 gmail|resend 토글.

- gmail: 개발용. GMAIL_USER + GMAIL_APP_PASSWORD(앱 비밀번호) 필요.
- resend: prod용. RESEND_API_KEY + 도메인 인증된 MAIL_FROM 필요.
"""
import smtplib
from email.mime.text import MIMEText

import httpx

from config import (
    GMAIL_APP_PASSWORD,
    GMAIL_USER,
    MAIL_FROM,
    MAIL_PROVIDER,
    RESEND_API_KEY,
)

SUBJECT = "[KNU AI Assistant] 가입 인증 코드"


def _body(code: str) -> str:
    return f"인증 코드: {code}\n\n10분 안에 입력해주세요. 본인이 요청하지 않았다면 이 메일을 무시하세요."


def send_verification_email(to: str, code: str) -> None:
    if MAIL_PROVIDER == "resend":
        _send_resend(to, code)
    elif MAIL_PROVIDER == "console" or not (GMAIL_USER and GMAIL_APP_PASSWORD):
        # 로컬 개발: 메일 설정이 없으면 실패시키지 않고 코드를 서버 로그에 출력.
        # (gmail/resend 설정이 있으면 자동으로 실제 발송 경로를 탄다)
        print(f"📧 [console mailer] {to} 인증 코드: {code}", flush=True)
    else:
        _send_gmail(to, code)


def _send_gmail(to: str, code: str) -> None:
    msg = MIMEText(_body(code))
    msg["Subject"] = SUBJECT
    msg["From"] = MAIL_FROM
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)


def _send_resend(to: str, code: str) -> None:
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        json={
            "from": MAIL_FROM,
            "to": [to],
            "subject": SUBJECT,
            "text": _body(code),
        },
        timeout=10,
    )
    resp.raise_for_status()
