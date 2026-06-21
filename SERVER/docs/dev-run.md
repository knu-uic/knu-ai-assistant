# 로컬 개발 서버 실행 가이드

네이티브 개발 기준(맥에서 직접 실행). `.env`는 `RUNTIME_ENV=local`.
전체 기능(로그인·공지·챗봇·동기화)을 쓰려면 **4개 + 웹 = 5개**가 다 떠 있어야 한다.

| # | 서비스 | 실행 위치 | 명령 |
|---|--------|-----------|------|
| 1 | db (postgres+pgvector) | `SERVER/` | `docker compose up -d db` |
| 2 | redis (잡 큐) | `SERVER/` | `docker compose up -d redis` |
| 3 | api (FastAPI) | `SERVER/` | `python -m uvicorn api.main:app --port 8000` |
| 4 | worker (arq — 동기화·공지 수집) | `SERVER/` | `arq workers.arq_worker.WorkerSettings` |
| 5 | web (React 개발 서버) | `WEB/` | `npm run dev` |

## 순서대로 전부 올리기

```bash
# 1+2. db, redis (도커)
cd ~/knu_ai_assistant/SERVER
docker compose up -d db redis

# 3. api — 새 터미널 (venv는 저장소 루트 .venv)
cd ~/knu_ai_assistant/SERVER
source ../.venv/bin/activate
python -m uvicorn api.main:app --port 8000

# 4. worker — 새 터미널 (포털/LMS 동기화, 공지 크론 수집 담당)
cd ~/knu_ai_assistant/SERVER
source ../.venv/bin/activate
arq workers.arq_worker.WorkerSettings

# 5. web — 새 터미널 (http://localhost:5173, /api는 vite가 8000으로 프록시)
cd ~/knu_ai_assistant/WEB
npm run dev
```

확인: 브라우저 `http://localhost:5173` 접속 → 로그인 →
공지/챗봇 동작하면 정상. api 단독 확인은 `curl localhost:8000/api/health`.

## 전부 내리기

```bash
# api / worker / web: 각 터미널에서 Ctrl+C
# (백그라운드로 띄웠으면: pkill -f "uvicorn api.main"; pkill -f "arq workers"; pkill -f vite)
cd ~/knu_ai_assistant/SERVER
docker compose stop db redis    # 데이터는 pgdata 볼륨에 남는다
```

## 자주 걸리는 것

- **api가 부팅에서 죽음** → db·redis가 먼저 떠 있는지 확인 (`docker ps`).
  `.env`·`.secrets/`가 `SERVER/` 바로 아래 있는지도 확인 (다른 위치면 env 누락으로 죽음).
- **동기화(포털/LMS)가 큐에서 안 빠짐** → worker(4번)가 안 떠 있는 경우. redis도 필요.
- **웹에서 API 호출 401/실패** → api(3번)가 안 떠 있거나, 토큰 만료(재로그인).
- **worker가 Ctrl+C로 안 죽음** → `kill -9` 필요할 때가 있음 (`pgrep -fl "arq workers"`로 PID 확인).
- 도커로 전체 스택을 한 번에 띄우는 prod 배포는 [prod-run.md](prod-run.md) 참고 — 이 문서는 네이티브 개발용.
