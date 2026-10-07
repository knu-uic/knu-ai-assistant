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

기본 개발 모드는 **배포용 실행 도구를 재사용하고 현재 repository의 Python 소스를 직접 실행**합니다.
Docker나 전역 Python/PostgreSQL/Redis, 루트 `.venv`는 사용하지 않습니다. Tauri 빌드용
Node.js 22+, Rust/Cargo와 OS 개발 도구는 필요합니다(macOS: Apple Command Line Tools,
Windows: Microsoft C++ Build Tools x64와 WebView2). 누락된 도구는 준비 명령이 안내하며
전역 도구를 몰래 설치하거나 삭제하지 않습니다.

```bash
cd server/manager
npm run setup:dev
npm run tauri dev
```

`setup:dev`는 다음 순서로 준비합니다. DB/API/worker는 아직 시작하지 않습니다.

- OS/CPU·빌드 도구 검사.
- 기존 `runtime/` 또는 macOS 설치 앱의 실행 도구만 재사용. 기존 데이터·비밀 설정은 복사하지 않음.
- 도구가 없는 Apple Silicon Mac은 검증된 0.2.3 GitHub DMG의 실행 도구를 SHA-256 검증 후
  `.dev/runtimes/`에 추출. 최초 다운로드는 큼.
  앱 버전과 준비용 도구 버전은 분리하므로 아직 릴리스하지 않은 코드도 개발 가능.
- Windows x64는 아래 네이티브 도구를 준비하고 pgvector를 MSVC로 빌드한 뒤 배포와 같은
  `stage:runtime` 수행. Windows 서비스나 전역 DB를 설치하지 않음.
- Python 의존성이 기존 묶음과 다르면 같은 Python 패치 버전으로 `.dev/python/`을 만들고
  requirements 설치. 설치 앱/공유 런타임에는 pip-install하지 않음.
- npm 라이브러리는 최초 또는 package-lock 변경 시 `npm ci`로 설치.
- `.dev/runtime.json` 작성.

이후 앱에서 서버 시작을 누르면 **최신 `server/api` 소스**로 실행됩니다. 개발 DB·자산·인증 정보·
Manager 설정·로그는 **`server/manager/.dev/data/`**에 저장됩니다. 설치 앱의 Application Support와
완전히 분리되며 `.dev/` 전체는 Git 제외입니다. 작은 Python 수정은 서버 중지→시작으로 반영됩니다.
requirements 변경은 준비 명령을 다시 실행하고 Manager 개발 앱도 재시작합니다. 오래된 설정이나
잘못된 OS 실행 도구는 시스템 Python으로 대체하지 않고 오류로 중지합니다.
LLM/Ollama 모델과 연결 설정은 별도로 준비해야 합니다.

직접 준비한 실행 도구 지정: `npm run setup:dev -- --runtime /absolute/path/to/runtime`.
Intel Mac/Linux는 자동 다운로드할 공개 도구가 없으므로 해당 OS/CPU의 runtime을 지정해야 합니다.
Windows ARM64는 현재 자동 준비 대상이 아닙니다. requirements에 비고정 버전도 있으므로 새로
설치한 라이브러리가 과거 묶음과 모두 같다고 보장하지 않습니다. 기존 묶음 재사용 시에는 그 묶음의
설치 결과를 그대로 사용합니다.

### Windows 네이티브 개발

- PostgreSQL 16.15-1: EDB 공식 Windows ZIP, 공급사 확인 SHA-256 고정.
- pgvector 0.8.6: 기존 릴리스와 같은 upstream commit 고정, `nmake /F Makefile.win`.
- Redis 7.2.15: 사용자가 선택한 `redis-windows/redis-windows` 커뮤니티 Cygwin 포트, SHA-256 고정.
  공식 Redis Windows 배포본이 아니며 호환 DLL도 함께 둠. Docker/WSL은 사용하지 않음.
- Node 22.23.1 공식 ZIP, Temurin JDK 21.0.12.1+1: 다운로드 SHA-256 고정.
- Python 3.12: uv managed Python과 같은 requirements/Playwright/OCR 준비 절차.

Redis/포트 라이선스와 출처를 보관합니다. Cygwin 및 동봉 DLL의 추가 라이선스·소스 제공 의무는
**공개 Windows 앱 재배포 전에 별도 검토**해야 합니다. 이번 준비 경로는 로컬 개발용이고
공개 Windows 릴리스를 자동 게시하지 않습니다. `.github/workflows/knu-native-development.yml`로
Windows/macOS 준비·단위 테스트·빈 DB에서 Manager 시작/종료를 검증합니다. 해당 Windows 작업의
성공 전에는 Windows 실행 검증 완료로 간주하지 않습니다.

### 기존 `.venv` 개발 모드

아래는 명시적으로 `KNU_LEGACY_DEV=1`을 지정할 때만 사용하는 기존 방식입니다.
Windows PowerShell에서는 `$env:KNU_LEGACY_DEV='1'`을 먼저 지정합니다.

먼저 repository 루트에 `.venv`를 만들고 `server/api/requirements.txt`를 설치합니다.
PostgreSQL과 Redis는 기존 KNU 서버 설정대로 실행되어 있어야 합니다.

```bash
cd server/manager
npm install
KNU_LEGACY_DEV=1 npm run tauri dev
```

Manager는 기본적으로 repository 루트의 `.venv/bin/python`
(Windows는 `.venv\\Scripts\\python.exe`)을 찾습니다. 다른 위치에서 실행할 때는:

```bash
KNU_SERVER_ROOT=/path/to/knu-ai-assistant \
KNU_PYTHON_PATH=/path/to/python KNU_LEGACY_DEV=1 npm run tauri dev
```

## 독립 실행형 릴리스

릴리스 번들은 운영자 PC의 Homebrew, Docker, Python 가상환경을
사용하지 않는다. 설치 패키지에 다음 런타임을 같은 OS·CPU용으로
포함한다.

- KNU FastAPI·crawler worker 소스
- portable Python 3.12, `requirements.txt` 라이브러리, Playwright Chromium
- PostgreSQL 16과 pgvector
- Redis
- PDF·HWP 처리용 Java runtime과 patched hwp2hwpx converter
- Codmes 공통 맥락 엔진 실행용 Node.js 22.23.1 (공식 배포본·체크섬 검증)

번들 빌드 머신에는 Node.js, Rust/Tauri, `uv`, JDK 21, C toolchain이
필요하지만 완성된 설치본 사용자에게는 필요하지 않다.

macOS·Linux에서 전용 native runtime을 먼저 빌드한다. 이 스크립트는
PostgreSQL 16.15, pgvector 0.8.6, Redis 7.2.15를 검증된 버전과
체크섬/commit으로 고정하고, 현재 CPU에 종속되는 pgvector 최적화는
비활성화한다.

```bash
export KNU_BUILD_JAVA_HOME=/path/to/jdk-21
bash server/manager/scripts/build-native-runtime.sh
```

스크립트가 출력한 경로를 번들 명령에 전달한다.

```bash
export KNU_POSTGRES_RUNTIME="$PWD/server/manager/native-runtime/darwin-arm64/postgres"
export KNU_REDIS_RUNTIME="$PWD/server/manager/native-runtime/darwin-arm64/redis"
export KNU_JAVA_RUNTIME="$PWD/server/manager/native-runtime/darwin-arm64/java"
export KNU_NODE_RUNTIME="$PWD/server/manager/native-runtime/darwin-arm64/node"
export KNU_BUILD_JAVA_HOME=/path/to/jdk-21

cd server/manager
npm run bundle
```

`stage:runtime`은 개발 PC의 PostgreSQL/Redis를 자동 탐지하지 않는다.
검증된 재배치 가능 런타임 경로가 하나라도 빠지면 릴리스 빌드를
즉시 실패시켜 불완전한 설치본이 나오지 않게 한다.

설치형 실행 시 Manager는 다음 순서를 자동 관리한다.

1. 전용 PostgreSQL 데이터 디렉터리 초기화 및 127.0.0.1:55433 시작
2. KNU DB 생성
3. 전용 Redis를 127.0.0.1:56379에서 시작
4. pgvector 포함 DB migration 실행
5. FastAPI 준비 후 crawler worker 시작
6. Manager 종료 시 worker, API, Redis, PostgreSQL 역순 종료

영구 데이터는 앱 번들 밖의 OS application-data 디렉터리에 보관한다.
`postgres/`, `redis/`, `assets/`, `config/`, `logs/`가 같은 루트 아래 생기므로
앱 업데이트가 DB와 첨부 자산을 덮어쓰지 않는다. `KNU_DATA_ROOT`로
운영 전용 디스크 경로를 지정할 수도 있다.

## 보안 경계

- 관리자 API는 앱이 기동할 때 만든 임의 토큰으로 보호됩니다.
- 토큰이 없는 서버는 loopback 접속만 관리 API를 허용합니다.
- API key와 수집 설정은 OS의 KNU Server Manager 앱 설정 디렉터리에 0600 권한으로 저장되며 API 응답에 key가 다시 노출되지 않습니다.
- Codex OAuth token은 `server/api/data/codex-auth.json`에 0600 권한으로 별도 저장되며 Manager API는 token을 반환하지 않습니다.
- Codmes의 계정 파일을 공유하지 않으므로 KNU Manager에서 로그아웃해도 Codmes와 ChatGPT에는 영향이 없습니다.
- 독립 실행형 설치본에는 Python/PostgreSQL/Redis/Java/Node를 포함합니다. 자격증명의 OS keychain 이전은 별도 개선 과제이며, 현재는 앱 전용 데이터 디렉터리의 접근 제한 파일과 학생별 암호화를 사용합니다.

## 배포 상태

### 0.2.3

- `client/`·`server/` 구조에 맞춘 API 탐색과 독립 실행 번들 경로.
- 웹·모바일 공유 대화 저장 및 Codmes 공통 맥락 엔진용 Node.js 포함.
- Ollama 이미지 분석의 실제 출력 상한 4,096토큰, 컨텍스트 8,192토큰,
  추론 OFF, 생성 전체 240초 제한과 잘린 결과 실패 처리.
- 공지 구조화 요청의 Ollama 출력 한도 전달 오류 수정.
- Node 배포본의 상대 링크 보존 및 앱 실행 중 Python 캐시가 서명된 번들에 추가되지 않도록 보호.

앱 교체는 기존 OS application-data 디렉터리의 DB·자산·설정·대화 기록을 유지한다.
로컬 설치와 GitHub 공개 배포는 같은 소스의 서로 다른 전달 단계다. 이 Mac에서는
설치 앱의 서버 시작·종료, 기존 DB 건수·모델 설정 유지, 번들 Node 맥락 엔진과
실행 후 앱 서명 무결성을 검증했다. Apple Developer ID 서명·공증 여부는 릴리스에
명시하며 로컬 검증 통과만으로 공증 완료를 의미하지 않는다.

기존 `.venv`·외부 PostgreSQL·Redis 방식은 `KNU_LEGACY_DEV=1`로 남겨 둔다.
기본 개발 모드는 `setup:dev`로 준비한 실행 도구와 최신 소스/별도 데이터를 쓴다.
`npm run bundle`은 위 도구를 포함하는 독립 실행형이다. `build-native-runtime.sh`는
macOS·Linux용이고, `build-windows-runtime.mjs`는 Windows x64 개발용 준비 경로다.
공개 Windows 설치본의 실제 검증·서명·재배포 라이선스 검토 및 릴리스 구성은 별도다.

초기 사용자용 배포는 macOS 14 이상을 대상으로 한다.
`knu-server-vX.Y.Z` tag를 push하면 `KNU Server Manager macOS release`
workflow가 독립 런타임을 build하고 DMG를 GitHub Release에 게시한다.
Apple 자격증명이 모두 있으면 Developer ID 서명과 Apple 공증을 수행하고,
없으면 앱을 ad-hoc 서명·무결성 검증한 뒤 `_unsigned.dmg`로 공개한다.
ad-hoc 서명은 Apple이 개발자 신원을 확인하거나 공증한 정식 서명이 아니다. tag 버전은
`server/manager/package.json`과 `src-tauri/tauri.conf.json`의 버전과
일치해야 한다. workflow를 수동 실행하면 서명하지 않은
개발 검증용 DMG만 artifact로 만든다.

정식 배포에는 다음 GitHub Actions secret이 필요하다.

- `MACOS_CERTIFICATE`: Developer ID Application `.p12`의 base64 문자열
- `MACOS_CERTIFICATE_PASSWORD`: `.p12` 비밀번호
- `APPLE_SIGNING_IDENTITY`: 인증서의 완전한 Developer ID Application 이름
- `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`: `notarytool` 공증 자격 증명

## Codex 인증

VLM 모델 화면에서 `OpenAI Codex (ChatGPT 계정)`을 고르고 로그인을 누르면
기본 브라우저의 OpenAI device login 페이지가 열립니다. Manager에 표시된
코드를 입력하면 계정이 등록되고, 해당 계정에 열려 있는 Codex 모델을
서버에서 조회해 선택할 수 있습니다. Codex 선택은 현재 OCR·표·이미지 설명
VLM 추출에 적용되며, 공지 구조화·RAG는 기존 서버 LLM 설정을 유지합니다.

Antigravity는 아직 제공자로 추가하지 않았습니다.

## 모델 선택

macOS 독립 실행형의 기본 로컬 구성은 Ollama
`gemma4:12b-mlx`(질문·답변)와 `bge-m3:latest`(1024차원 임베딩)를 사용합니다.
Ollama에서 두 모델을 먼저 설치하면 별도 환경변수 없이 서버를 시작할 수 있습니다.

임베딩은 제공자·모델·출력 차원별 독립 데이터셋으로 보관한다. Manager가 새
데이터셋을 끝까지 생성한 뒤에만 활성 검색 데이터셋을 원자적으로 바꾸므로 생성
중이거나 실패해도 기존 모델이 계속 검색을 담당한다. 완료된 데이터셋은 다시
생성하지 않고 즉시 선택할 수 있으며, 비활성 데이터셋만 개별 삭제할 수 있다.
새 공지가 들어오면 보관 중인 데이터셋도 수집 완료 뒤 백그라운드에서 동기화한다.

출력 차원은 데이터셋마다 다르게 지정할 수 있다. 2,000차원 이하는 모델별 HNSW
부분 인덱스를 사용하고, 그보다 큰 데이터셋은 정확 검색을 사용한다. Qwen3
Embedding처럼 MRL을 지원하는 모델은 저장공간과 검색 속도를 위해 1024차원
출력을 기본 권장한다. 모델 설정 화면의 데이터셋 목록에서 상태, 공지·청크 수,
용량, 검색 방식과 실시간 생성 진행률을 확인할 수 있다.

모델 이름을 직접 입력하지 않습니다. 제공자 선택 시 Manager가 해당 제공자의
모델 API를 조회해 드롭다운을 채웁니다. LM Studio는 `api/v1/models`, Ollama는
`api/tags`를 사용하며 Base URL을 바꾸거나 `목록 새로고침`을 누르면 다시
조회합니다. 로컬 제공자는 앱이 실행 중이어야 하며, 원격 API 제공자는 API key를
입력한 뒤 목록을 새로고침합니다.
