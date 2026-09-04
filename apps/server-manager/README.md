# KNU Server Manager

KNU plugin server를 관리하는 독립 데스크톱 앱입니다. Codmes Server Manager의 부분이 아니며,
KNU plugin/server 운영자가 따로 배포하고 관리합니다.

## 현재 기능

- FastAPI와 ARQ crawler worker 동시 실행·종료
- Ollama, LM Studio, OpenAI API, Gemini API, OpenAI Codex VLM 선택·연결 테스트
- 제공자별 사용 가능 모델 자동 조회와 선택 (Ollama 임베딩 전용 모델은 제외)
- Codex ChatGPT 브라우저 로그인, 다중 계정 선택, 개별 로그아웃, 사용 가능 모델 조회
- 독립된 `수집 관리` 메뉴에서 수집 설정과 문서 분석 모델 관리
- `데이터` 메뉴에서 저장 결과 조회·검수
- 자동 수집 ON/OFF 및 1시간, 6시간, 12시간, 1일 주기
- 수동·자동이 공유하는 전체, 최근 7일, 지정 페이지 범위·소스·추출 설정
- 게시판별 수집 대상 선택
- PostgreSQL에 저장된 공지 본문·구조화 메타데이터·첨부 추출 결과 조회
- 전체 공지 DB·자산 파일 용량과 공지별 실제 보관 용량 확인
- 공지 소스·카테고리·시작일~종료일 날짜 범위·현재/과거 공지·추출 버전 필터
- 공지 HTML 본문 및 HWP/HWPX/Word/PDF/PowerPoint/Excel 그림의 배치 번호·앞뒤 문맥·VLM 설명·원본 이미지 미리보기
- KNU 서비스 계정과 연결 학적 정보 수정·삭제
- `Tool` 메뉴에서 FastMCP 런타임이 실제 공개하는 도구, 그룹, 입력 JSON Schema와
  읽기/쓰기·파괴적 작업 여부 조회
- API/worker 로그 조회
- 창을 닫아도 메뉴 막대(macOS) 또는 system tray(Windows/Linux)에서 서버 계속 실행
- tray에서 Manager 열기, 서버 실행·종료, 앱 완전 종료 및 macOS Dock icon 선택 표시

공주대 공식 포털 비밀번호는 저장하지 않으며, Manager는 공식 포털 계정을 수정·삭제하지 않습니다.
Manager를 열어도 서버는 자동으로 시작되지 않습니다. 대시보드의 `서버 시작` 버튼을 눌러야 FastAPI와 crawler worker가 함께 시작됩니다. PostgreSQL·Redis
연결 등의 이유로 시작하지 못하면 앱은 그대로 열리고 `서버 로그`에 원인을 남깁니다.
이전 인스턴스가 8000번 포트를 사용 중이면 새 worker를 따로 시작하지 않고 충돌을
명확히 표시합니다. API가 실제로 준비된 뒤에만 crawler worker를 시작합니다.

도구 목록은 별도 `tools.json` 복사본이 아니라 FastMCP의 실제 등록부에서 직접
읽습니다. KNU Manager는 서버가 무엇을 공개하는지 확인하는 운영자 화면이며,
각 Workspace에서 도구를 사용할지에 대한 승인은 Codmes Server Manager가 담당합니다.

## 크롤링 중복 처리

중복 판단은 페이지 번호가 아닌 정규화된 공지 URL로 한다. 전체 수집은
중간 페이지가 모두 기존 URL이어도 종료하지 않고 실제 마지막 페이지까지
목록을 확인한다. `completed`인 과거 URL은 상세 본문·첨부파일을 다시
처리하지 않고, 신규·실패 URL을 처리한다. 최근 7일
공지는 수정 가능성을 고려해 완료 URL이어도 다시 확인한다.
이전 추출 버전의 완료 공지는 수동 수집에서 `이전 추출 버전도 갱신`을
체크한 경우에만 현재 버전으로 재처리한다. 저장 데이터 목록과 상세에서
각 공지의 실제 추출 버전을 확인할 수 있다.

자동 수집은 수동 수집과 같은 범위·소스·추출 설정을 사용한다. 수동 `전체 페이지`는 누락 검사나
최초 수집에 사용하며, 부분 수집 이력은 이후 전체 수집의 종료 조건으로
사용하지 않는다.

자동 수집 토글을 켜면 별도의 `수집 시작` 클릭 없이 설정한 주기에 따라
실행된다. 자동 수집이 켜진 동안은 수동 수집과 설정 변경을 막아 동시 작업
충돌을 피한다. 토글·주기·범위·소스·추출 설정은 Manager 재시작 후에도
그대로 유지된다.

Server Manager의 `수집 관리 > 수집 설정`에서 자동 수집을 OFF로 바꾸어야 수동 수집을 시작하거나 설정을 변경할 수 있다. 자동 수집 ON/OFF와 공통 수집 설정은 앱 전용 영구 설정 파일에 보관된다.

## 개발 실행

먼저 repository 루트에 `.venv`를 만들고 `services/api/requirements.txt`를 설치합니다.
PostgreSQL과 Redis는 기존 KNU 서버 설정대로 실행되어 있어야 합니다.

```bash
cd apps/server-manager
npm install
npm run tauri dev
```

Manager는 기본적으로 repository 루트의 `.venv/bin/python`
(Windows는 `.venv\\Scripts\\python.exe`)을 찾습니다. 다른 위치에서 실행할 때는:

```bash
KNU_SERVER_ROOT=/path/to/knu-ai-assistant \
KNU_PYTHON_PATH=/path/to/python npm run tauri dev
```

## 보안 경계

- 관리자 API는 앱이 기동할 때 만든 임의 토큰으로 보호됩니다.
- 토큰이 없는 서버는 loopback 접속만 관리 API를 허용합니다.
- API key와 수집 설정은 OS의 KNU Server Manager 앱 설정 디렉터리에 0600 권한으로 저장되며 API 응답에 key가 다시 노출되지 않습니다.
- Codex OAuth token은 `services/api/data/codex-auth.json`에 0600 권한으로 별도 저장되며 Manager API는 token을 반환하지 않습니다.
- Codmes의 계정 파일을 공유하지 않으므로 KNU Manager에서 로그아웃해도 Codmes와 ChatGPT에는 영향이 없습니다.
- 실제 배포판은 OS keychain 저장과 Python/PostgreSQL/Redis 포함 패키징이 추가로 필요합니다.

## 배포 상태

현재 Manager는 저장소 개발 환경의 Python 가상환경과 별도 PostgreSQL·Redis를
사용하는 운영자용 개발 앱이다. Tauri 소스 버전은 `0.1.0`이지만 독립 설치본
GitHub Release는 아직 발행하지 않는다. 일반 사용자용 설치본으로 배포하려면 운영체제별
Python runtime, DB·Redis 생명주기, OS keychain을 패키지에 포함한 후 별도 배포
워크플로우를 추가해야 한다.

## Codex 인증

VLM 모델 화면에서 `OpenAI Codex (ChatGPT 계정)`을 고르고 로그인을 누르면
기본 브라우저의 OpenAI device login 페이지가 열립니다. Manager에 표시된
코드를 입력하면 계정이 등록되고, 해당 계정에 열려 있는 Codex 모델을
서버에서 조회해 선택할 수 있습니다. Codex 선택은 현재 OCR·표·이미지 설명
VLM 추출에 적용되며, 공지 구조화·RAG는 기존 서버 LLM 설정을 유지합니다.

Antigravity는 아직 제공자로 추가하지 않았습니다.

## 모델 선택

모델 이름을 직접 입력하지 않습니다. 제공자 선택 시 Manager가 해당 제공자의
모델 API를 조회해 드롭다운을 채웁니다. LM Studio는 `api/v1/models`, Ollama는
`api/tags`를 사용하며 Base URL을 바꾸거나 `목록 새로고침`을 누르면 다시
조회합니다. 로컬 제공자는 앱이 실행 중이어야 하며, 원격 API 제공자는 API key를
입력한 뒤 목록을 새로고침합니다.
