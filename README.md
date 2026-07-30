# KNU AI Assistant

공주대학교 포털·LMS·공지 데이터를 웹과 Codmes에 제공하는 모노레포입니다.
웹, API 서버, Codmes 플러그인은 같은 도메인 계약을 사용하지만 배포 단위는 서로
분리되어 있습니다.

## 저장소 구조

```text
apps/web/                    React/Vite 기반 독립 KNU 웹
services/api/                FastAPI, MCP, 수집·동기화 worker
packages/codmes-plugin/      Codmes용 manifest, Surface, Tool 선언
docs/                        KNUIS·로그인 조사 문서
tools/knuis-debugger/        KNUIS 통신을 확인하는 개발 도구
```

`packages/codmes-plugin`은 KNU 웹을 WebView로 여는 코드가 아닙니다. KNU API가
JSON 데이터를 제공하면 플러그인의 `surface.json`이 화면 구조와 데이터 바인딩을
선언하고 Codmes가 네이티브 UI로 렌더링합니다. 같은 패키지의 `tools.json`은 AI가
사용할 MCP 도구를 선언합니다.

## 로컬 개발 조건

각 개발 서버 컴퓨터에는 다음 조건이 충족되어 있어야 합니다.

- Python 3.12 가상환경이 저장소 루트의 `.venv`에 준비되어 있음
- `services/api/.env`가 작성되어 있음
- PostgreSQL 16과 pgvector를 사용할 수 있음
- Docker를 통해 PostgreSQL과 Redis를 실행할 수 있음
- 웹을 개발한다면 Node.js와 `apps/web/node_modules`가 준비되어 있음
- Codmes 플러그인을 시험한다면 Codmes CLI와 Workspace가 준비되어 있음

최초 환경 구성과 세부 환경 변수는
[API 개발 실행 문서](services/api/docs/dev-run.md)와
[`services/api/.env.example`](services/api/.env.example)을 참고합니다.

## 평소 로컬 실행

저장소 루트에서 DB와 Redis를 먼저 실행합니다.

```sh
cd services/api
docker compose up -d db redis
```

API 서버와 동기화 worker는 서로 다른 터미널에서 실행합니다.

```sh
cd services/api
source ../../.venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```sh
cd services/api
source ../../.venv/bin/activate
arq workers.arq_worker.WorkerSettings
```

독립 KNU 웹도 개발할 때만 세 번째 터미널에서 실행합니다.

```sh
cd apps/web
npm run dev
```

## Codmes 플러그인 설치

로컬 소스를 개발 중인 Codmes Workspace에 설치하려면 Codmes 저장소에서 실행합니다.

```sh
cd /path/to/Codmes
node bin/codmes.mjs plugin install \
  /path/to/knu-ai-assistant/packages/codmes-plugin \
  --root /path/to/CodmesWorkspace
```

일반 사용자는 이 경로를 직접 다루지 않고 Codmes Marketplace에서 KNU를 설치합니다.
배포 시에는 전체 저장소가 아니라 `packages/codmes-plugin`에서 생성한 서명 package만
Marketplace에 등록합니다.

## 구성 요소의 책임

| 구성 요소 | 책임 |
|---|---|
| `apps/web` | 독립 웹 제품의 화면과 웹 전용 사용자 흐름 |
| `services/api` | 학교 로그인, 데이터 동기화·저장, JSON API, MCP 도구 실행 |
| `packages/codmes-plugin` | Codmes 네이티브 화면 규약과 MCP 도구 선언 |
| Codmes 서버 | 플러그인 설치·검증, 자격 증명 보관, API/MCP 중계, AI 도구 호출 |
| Codmes Apple 앱 | 선언된 Surface를 SwiftUI로 표시하고 사용자 입력을 전달 |

포털 비밀번호는 인증과 동기화 작업에만 사용하고 영속 저장하지 않습니다. KNU 사용자
데이터는 KNU 서버가 사용하는 PostgreSQL에 저장되며, Codmes 서버는 KNU가 발급한
사용자 세션과 MCP 서비스 자격 증명을 Codmes Workspace에 보관합니다.

