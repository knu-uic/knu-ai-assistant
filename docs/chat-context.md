# KNU 대화 저장과 Codmes 공통 맥락 엔진

## 무엇을 공유하고 무엇을 분리하는가

Codmes의 기존 token budget, compaction planner, native/의미 요약/fallback 흐름을
`Codmes/packages/context-engine`의 의존성 없는 JavaScript 모듈로 추출했다. Codmes
runtime도 이 공통 모듈에 위임한다. KNU는 같은 파일의 고정 snapshot을
`server/api/third_party/codmes-context-engine`에 포함한다. Hermes 전체 엔진이나
별도의 Python 압축 알고리즘을 넣은 것이 아니다.

KNU FastAPI → Node JSONL 실행 어댑터 → 공통 엔진 → Python의 기존 모델 호출
어댑터 → KNU PostgreSQL 순서다. Node 프로세스는 요청마다 독립 실행되고 별도
포트를 열지 않으며, 계정·API 키·Codmes 파일·세션 저장소에 접근하지 않는다.
공유되는 것은 **맥락 관리 코드**뿐이다. 학생의 대화와 계정은 Codmes 데이터와 분리한다.

## 맥락 유지

원본은 PostgreSQL에 저장한다. 새 웹·앱은 대화 ID, revision, 요청 UUID, 질문만 전송하고
서버가 인증된 학생의 원본을 읽는다. 기존 서버의 `history[-12:]`는 제거했다.

- 임계값 아래에서는 이전 원문을 전달한다. 최근 메시지 개수로 자르지 않는다.
- 임계값에 도달하면 OpenAI Responses 계열은 native `/responses/compact`를 우선 시도한다.
- 지원하지 않거나 실패하면 선택된 모델로 의미 요약하고 토큰 목표에 맞는 최근 원문을 함께 전달한다.
- checkpoint는 학생·계정·모델 범위를 구분해서 DB에 저장한다. 모델 변경 시 기존 checkpoint를 재사용하지 않는다.
- 원본은 요약과 무관하게 유지한다. 다른 대화는 자동 주입하지 않고 모델이
  `knu_history_search`/`knu_history_read`로 **본인의 기록만** 검색·분할 조회한다.
- 요약 실패 시 원문으로 돌아가되 입력 한도 초과는 명시적 413 오류로 알린다. 몰래 잘라 보내지 않는다.

토큰 수는 Codmes의 문자 종류별 **추정치**이며 정확한 제공사 tokenizer 계산이 아니다.
질문·시스템 지시·도구 schema도 입력 예산에 포함하고 출력 공간을 남긴다.
클라우드 모델 한도를 이름만으로 추측하지 않고 미설정 시 보수적인 8,192를 사용한다.
Ollama는 로드된 runner의 실제 `context_length`를 조회한다.

```dotenv
# 별도 경로가 필요할 때만. 개발 환경은 PATH의 node 사용 가능.
KNU_CONTEXT_NODE=/absolute/path/to/node
# 확인된 실제 모델 한도보다 크게 설정하지 않는다.
KNU_CHAT_CONTEXT_WINDOW=8192
# provider:model별 설정이 전역 값보다 우선한다.
KNU_CHAT_CONTEXT_LIMITS={"provider:model-id":8192}
```

KNU 모델 호출/도구 실행 자체는 기존 Python 코드를 유지한다. **Codmes의 전체 agent
runtime이나 turn 내부 tool-loop 압축까지 이식한 것은 아니다.** 한 turn에서 도구 결과가
예산을 넘으면 413으로 중단한다. 매우 긴 가져오기 기록의 요약 입력 자체가 모델 한도를
넘는 경우도 오류를 알리므로 더 큰 맥락 모델이나 새 대화가 필요하다. 의미 요약은
모델의 추가 호출로 비용·지연이 발생할 수 있고, 내용의 완벽한 기억을 보장하지 않는다.

## 데이터와 충돌 방지

`018_student_chat_history.sql`, `019_student_chat_context.sql`은 학번별 원본,
revision, checkpoint, 마지막 요청 UUID를 저장한다. 서버만 checkpoint를 작성한다.
API는 인증된 학번으로 모든 읽기·쓰기·검색을 제한한다. 다른 학생 UUID는 접근할 수 없다.

동일 대화의 생성 요청은 PostgreSQL row lock으로 여러 API 프로세스와 기기 사이에서도
보호한다. 질문·답변·checkpoint는 한 transaction으로 반영하고 실패/취소 시 rollback한다.
이미 완료한 같은 요청 UUID 재시도는 저장된 답변을 반환한다. 다른 기기의 오래된
revision 수정은 409이며 기존 기록을 덮어쓰지 않는다. 연결이 끊긴 웹·앱은 해당 UUID를
다시 조회하여 이미 저장된 답변을 복원한다.

원본 저장 안전 한도는 대화당 10,000개 메시지·총 1,000,000자, 개별 메시지 100,000자다.
질문은 10,000자 이하다. 이것은 저장/요청 자원 보호이며 모델 맥락을 개수로 자르는 정책이 아니다.
한도에 도달하면 새 대화를 안내하고 이전 기록은 남긴다.

웹의 옛 `knu_chat_계정` 브라우저 기록은 **대화 목록 → 기존 브라우저 기록 가져오기**로
사용자가 확인 후 업로드한다. 중복 import는 같은 원본 ID를 재사용하고 브라우저 원본은 삭제하지 않는다.
로그아웃/앱 삭제는 서버 대화 삭제가 아니다. 목록의 삭제는 해당 KNU 서버 기록을 모든 기기에서 삭제한다.

## 설치와 배포

개발 서버는 Node.js 22+를 준비하고, 적용 전 운영 DB를 백업한 뒤 다음을 실행한다.

```sh
cd server/api
../../.venv/bin/python -m db.migrate
```

이미 적용된 migration은 재실행하지 않는다. API 실행만으로 migration이 자동 적용되지는 않는다.
Manager는 서버 시작마다 기존 migration runner를 호출한다. 개발 터미널에서 API를
직접 실행하는 경우에는 위 명령을 먼저 실행해야 한다. 기존 설치본 업그레이드에서도
Manager 로그에서 새 migration 적용 여부를 확인한다.

API Docker 이미지에는 Node를 포함한다. Server Manager의 native/runtime staging도 공식
portable Node를 포함하며 실행 경로를 `KNU_CONTEXT_NODE`로 전달한다. 준비 스크립트는
다운로드 SHA-256을 확인한다. 개발 PC의 Node 경로를 설치본에 의존시키지 않는다.
Manager 0.2.3 설치 패키지는 이 Mac에서 실제 빌드·설치했고, 기존 데이터 유지와
번들 Node 엔진 실행 및 서버 시작·종료를 검증했다. Docker 이미지 자체의 배포 빌드는
아직 검증하지 않았다. 공개 설치본은 GitHub 릴리스의 빌드 결과와 배포 상태를 확인한다.

## 검증 및 snapshot 갱신

`snapshot.json`은 추출 기준 Codmes commit과 파일 hash를 기록한다. 현재 추출은 두
저장소의 로컬 변경이며 upstream에 이미 게시된 commit이 있다는 뜻은 아니다.
업데이트할 때 양쪽 공통 모듈과 snapshot/hash를 함께 갱신하고 아래 테스트를 실행한다.

```sh
# Codmes 저장소
npm run check
# KNU API; 운영 DB 대신 테스트용 임시 PostgreSQL DSN을 명시
KNU_CONTEXT_TEST_DSN='postgresql://disposable-test-db' ../../.venv/bin/python -m pytest tests -q
# 선택: 두 저장소의 공통 파일이 byte-identical인지 추가 확인
KNU_CODMES_CONTEXT_SOURCE='/path/to/Codmes/packages/context-engine' ../../.venv/bin/python -m pytest tests/test_context_snapshot.py -q
# 선택: Vite가 로컬에서 실행 중일 때, 모든 API를 mock하는 브라우저 테스트
KNU_WEB_TEST_URL=http://127.0.0.1:5183 ../../.venv/bin/python -m pytest tests/test_web_conversations_browser.py -q
```

SQL 통합 테스트는 지정한 테스트 DB 안에 임의 schema를 만들고 그 schema만 제거한다.
운영 DSN을 사용하지 않는다. 모델은 mock으로 검증하며 실제 학교 계정·유료 AI를 호출하지 않는다.

현재 로컬 검증: Codmes 349개 통과/기존 5개 skip, 최종 번들 Python으로 KNU API
335개 통과/opt-in 2개 skip, 별도 일회용 PostgreSQL 및 mock 브라우저 시나리오 통과,
웹 변환 테스트 5개·production build 통과, 모바일 공통 테스트 21개·Debug/unsigned
Release build·lint 통과, Manager Node 테스트 3개·TypeScript 및 Rust 테스트 8개 통과.
lint에는 의존성 업데이트 권고와 의도적인 Debug HTTP 경고가 남는다.
웹 개발 의존성은 Vite 7.3.7 / React plugin 5.2.0 및 호환 transitive patch로 갱신했다.
기존 취약점 7개는 현재 `npm audit` 기준 0개이며 production build, 변환 테스트와
mock 브라우저 시나리오를 다시 검증했다. React 18과 기존 브라우저 build target은 유지한다.
Node.js는 22.12+를 권장한다. [Vite 7 공식 마이그레이션 안내](https://v7.vite.dev/guide/migration.html)를 참고한다.
