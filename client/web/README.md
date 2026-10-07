# KNU PICK — Web (React + Vite)

## 로컬 실행 — 4개 서비스가 모두 떠 있어야 동기화가 동작한다

동기화(포털·LMS)는 백그라운드 워커가 처리한다. **워커나 redis가 없으면 동기화는 영원히 "동기화 중..."에서 멈춘다.**

```bash
# 1) DB + Redis (API 서비스에서)
cd server/api && docker compose up -d db redis

# 1.5) 최초 설치·업데이트 후 DB 마이그레이션
cd server/api && RUNTIME_ENV=local ../../.venv/bin/python -m db.migrate

# 2) API 서버
cd server/api && RUNTIME_ENV=local ../../.venv/bin/python -m uvicorn api.main:app --port 8000

# 3) 워커 (동기화 처리 — 필수!)
cd server/api && RUNTIME_ENV=local ../../.venv/bin/arq workers.arq_worker.WorkerSettings

# 4) 웹
cd client/web && npm install && npm run dev   # → http://localhost:5173
```

`/api` 요청은 vite proxy로 8000(API)으로 전달된다(같은 오리진).

### Codmes Surface에서 로컬 실행

Codmes plugin proxy 아래에서는 production build의 상대 asset 경로를 사용한다.

```bash
cd client/web
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

`npm run dev`는 KNU 웹 자체 개발용이다. Vite HMR이 root-absolute 경로를 사용하므로
Codmes의 `/api/plugins/.../surface/` 아래에서 직접 여는 실행 방식으로는 사용하지
않는다.

## 인증

별도 회원가입 없이 공주대 포털 학번·비밀번호로 로그인한다. 포털 비밀번호는 서버 DB에 저장하지 않는다.

웹 대화 화면에서 **학교 제공 모델**과 **학생 본인의 모델** 중 하나를 명시적으로
선택한다. 학교 모델은 서버매니저에서 별도로 켜는 Ollama/LM Studio 로컬 모델이나
학교 공용 OpenAI/Gemini API 키를 사용할 수 있다. 공지 크롤링·정제 설정과는
독립적이다. 개인 모델은 프로필 화면에서 연결한 Codex 계정 또는 본인의 OpenAI/Gemini
API 키를 사용한다. KNU 서버는 개인
자격증명을 학번별로 암호화해 보관하고 Codex 토큰이 만료되면 갱신한다. 선택한
경로가 사용 불가하면 409 오류를 반환하며 다른 계정이나 모델로 자동 대체하지 않는다.

대화 API는 `POST /api/chat/stream`에 질문과 최근 대화 기록을 JSON으로 전송한다.
모델은 KNU MCP의 읽기 도구를 선택해 호출한다. 상담 접수 같은 쓰기 도구는 웹의
명시적 최종 승인 UI가 준비되기 전까지 제공하지 않는다.

## 빌드

```bash
npm run build   # → dist/ (caddy 정적 서빙)
```
