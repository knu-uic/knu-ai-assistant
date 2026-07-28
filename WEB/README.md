# KNU PICK — Web (React + Vite)

## 로컬 실행 — 4개 서비스가 모두 떠 있어야 동기화가 동작한다

동기화(포털·LMS)는 백그라운드 워커가 처리한다. **워커나 redis가 없으면 동기화는 영원히 "동기화 중..."에서 멈춘다.**

```bash
# 1) DB + Redis (SERVER에서)
cd SERVER && docker compose up -d db redis

# 2) API 서버
cd SERVER && RUNTIME_ENV=local ../.venv/bin/python -m uvicorn api.main:app --port 8000

# 3) 워커 (동기화 처리 — 필수!)
cd SERVER && RUNTIME_ENV=local ../.venv/bin/arq workers.arq_worker.WorkerSettings

# 4) 웹
cd WEB && npm install && npm run dev   # → http://localhost:5173
```

`/api` 요청은 vite proxy로 8000(API)으로 전달된다(같은 오리진).

### Codmes Surface에서 로컬 실행

Codmes plugin proxy 아래에서는 production build의 상대 asset 경로를 사용한다.

```bash
cd WEB
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

`npm run dev`는 KNU 웹 자체 개발용이다. Vite HMR이 root-absolute 경로를 사용하므로
Codmes의 `/api/plugins/.../surface/` 아래에서 직접 여는 실행 방식으로는 사용하지
않는다.

## 가입 인증 코드

`MAIL_PROVIDER=console`(기본)이면 인증 코드가 **API 서버 터미널 로그**에 출력된다:

```
📧 [console mailer] you@smail.kongju.ac.kr 인증 코드: 123456
```

실제 메일 발송은 `.env`에 `GMAIL_USER` + `GMAIL_APP_PASSWORD`(Gmail 앱 비밀번호) 또는 `MAIL_PROVIDER=resend` + 키.

## 빌드

```bash
npm run build   # → dist/ (caddy 정적 서빙)
```
