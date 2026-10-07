# 로컬 개발 서버 실행 가이드

Server Manager로 최신 소스를 개발하려면 [독립 개발 환경](../../manager/README.md#개발-실행)의
`npm run setup:dev` → `npm run tauri dev`를 우선 사용한다. 이 경로는 배포용 네이티브
실행 도구와 별도 개발 DB를 쓰며 Docker/루트 `.venv`가 필요하지 않다.
아래는 API/worker를 직접 띄우는 기존 `.venv`·Docker DB 개발 방식이다.

네이티브 개발 기준(맥에서 직접 실행). `.env`는 `RUNTIME_ENV=local`.
전체 기능(로그인·공지·챗봇·동기화)을 쓰려면 **4개 + 웹 = 5개**가 다 떠 있어야 한다.

채팅 맥락 엔진에는 Node.js 22+가 필요하다. Node는 API가 요청별로 실행하므로 따로
서버 포트를 열지 않는다. 서버 업그레이드 전 DB를 백업하고 `python -m db.migrate`로
새 대화 migration을 적용한다. 자세한 범위와 환경 변수는
[대화 저장·공통 엔진 안내](../../../docs/chat-context.md)를 참고한다.

| # | 서비스 | 실행 위치 | 명령 |
|---|--------|-----------|------|
| 1 | db (postgres+pgvector) | `server/api/` | `docker compose up -d db` |
| 2 | redis (잡 큐) | `server/api/` | `docker compose up -d redis` |
| 3 | api (FastAPI) | `server/api/` | `python -m uvicorn api.main:app --port 8000` |
| 4 | worker (arq — 동기화·공지 수집) | `server/api/` | `arq workers.arq_worker.WorkerSettings` |
| 5 | web (React 개발 서버) | `client/web/` | `npm run dev` |

## 순서대로 전부 올리기

```bash
# 1+2. db, redis (도커)
cd ~/knu-ai-assistant/server/api
docker compose up -d db redis

# 3. api — 새 터미널 (venv는 저장소 루트 .venv)
cd ~/knu-ai-assistant/server/api
source ../../.venv/bin/activate
python -m uvicorn api.main:app --port 8000

# 4. worker — 새 터미널 (포털/LMS 동기화, 공지 크론 수집 담당)
cd ~/knu-ai-assistant/server/api
source ../../.venv/bin/activate
arq workers.arq_worker.WorkerSettings

# 5. web — 새 터미널 (http://localhost:5173, /api는 vite가 8000으로 프록시)
cd ~/knu-ai-assistant/client/web
npm run dev
```

확인: 브라우저 `http://localhost:5173` 접속 → 로그인 →
공지/챗봇 동작하면 정상. api 단독 확인은 `curl localhost:8000/api/health`.

## 전부 내리기

```bash
# api / worker / web: 각 터미널에서 Ctrl+C
# (백그라운드로 띄웠으면: pkill -f "uvicorn api.main"; pkill -f "arq workers"; pkill -f vite)
cd ~/knu-ai-assistant/server/api
docker compose stop db redis    # 데이터는 pgdata 볼륨에 남는다
```

## 자주 걸리는 것

- **api가 부팅에서 죽음** → db·redis가 먼저 떠 있는지 확인 (`docker ps`).
  `.env`·`.secrets/`가 `server/api/` 바로 아래 있는지도 확인 (다른 위치면 env 누락으로 죽음).
- **동기화(포털/LMS)가 큐에서 안 빠짐** → worker(4번)가 안 떠 있는 경우. redis도 필요.
- **웹에서 API 호출 401/실패** → api(3번)가 안 떠 있거나, 토큰 만료(재로그인).
- **worker가 Ctrl+C로 안 죽음** → `kill -9` 필요할 때가 있음 (`pgrep -fl "arq workers"`로 PID 확인).
- 도커로 전체 스택을 한 번에 띄우는 prod 배포는 [prod-run.md](prod-run.md) 참고 — 이 문서는 네이티브 개발용.

## 설치된 Server Manager의 데이터를 유지한 모바일 개발 테스트

기존 Docker 개발 DB와 설치된 Manager의 DB는 별개일 수 있다. 기존 데이터를 사용하려면
**Server Manager 앱을 종료한 뒤** 정확한 데이터 디렉터리를 선택한다. 이 경로의
`postgres/PG_VERSION`, `config/runtime-secrets.json`이 있어야 한다. 비밀값을 채팅·로그에
복사하지 않는다. 아래 도우미는 저장된 연결 정보와 학교 모델 설정을 현재 소스에 연결하며,
네이티브 서비스 시작·종료나 학생 인증 우회는 하지 않는다.

```sh
# server/api에서 실행. DB와 Redis는 Manager의 기존 런타임으로 먼저 시작한다.
../../.venv/bin/python dev_manager.py inspect \
  --data-root '/Users/user/Library/Application Support/kr.ac.kongju.knu-server-manager' \
  --runtime-root '/Applications/KNU Server Manager.app/Contents/Resources/runtime'

# 새 터미널에서 각각 api, worker를 실행한다. Node.js 22+도 필요하다.
../../.venv/bin/python dev_manager.py api \
  --data-root '/Users/user/Library/Application Support/kr.ac.kongju.knu-server-manager' \
  --runtime-root '/Applications/KNU Server Manager.app/Contents/Resources/runtime'
../../.venv/bin/python dev_manager.py worker \
  --data-root '/Users/user/Library/Application Support/kr.ac.kongju.knu-server-manager' \
  --runtime-root '/Applications/KNU Server Manager.app/Contents/Resources/runtime'
```

이 worker는 개발 프로세스 안에서만 정기 크롤링·세션 유지 cron을 끈다. 사용자가
요청한 로그인/학사 동기화는 가능하며 저장된 운영 설정은 변경하지 않는다.
API는 `127.0.0.1:8000`, 에뮬레이터는 `http://10.0.2.2:8000`으로 연결한다.

새 대화 테이블 적용은 DB 정지 상태의 PostgreSQL 디렉터리 백업을 먼저 만들고
원본과 일치하는지 검증한 후 `dev_manager.py migrate --backup-root <검증한 백업 디렉터리>`에
위 두 경로 옵션을 함께 지정한다. 도우미는 018/019 이외의 미적용 migration을 거부하고,
별도 SQL dump도 저장한 다음 기존 테이블의 행 수를 비교한다. 이미 존재하는 dump를
덮어쓰지 않는다. 백업에는 인증 정보가 포함될 수 있으므로 접근 권한을 제한한다.

테스트 종료 시 api/worker/web 터미널을 Ctrl+C로 종료하고, 테스트에 직접 시작한
Redis와 PostgreSQL만 정상 종료한 뒤 설치된 Manager 앱을 다시 연다.
**설치된 앱 번들은 현재 소스로 자동 교체되지 않는다.** 구버전 번들로는 새 대화 API나
Node 기반 맥락 엔진을 사용할 수 없으며, 이 테스트가 새 Manager 릴리스 검증을 대신하지 않는다.
