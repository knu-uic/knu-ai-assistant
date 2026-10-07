# KNU PICK 모바일 — Android 우선

Android Studio에서 이 `client/mobile` 폴더를 **Open** 한다. Kotlin Multiplatform(KMP)과
Compose Multiplatform(CMP) 프로젝트이며 화면·상태·API 코드는 `shared/commonMain`,
Android 실행·암호화 저장소는 `androidApp`에 있다. Android에서는 Jetpack Compose로
렌더링한다. 웹을 WebView로 감싼 앱이 아니다.

## 실행

Android Studio의 SDK Manager에서 Android SDK 37을 설치하고 Gradle Sync 후
`androidApp`을 Android 에뮬레이터 또는 기기에서 실행한다. 최소 Android 8.0(API 26).
Gradle JDK는 Android Studio 내장 JBR을 사용한다. 이 Mac에서는 JBR 25로 검증했다.

```sh
./gradlew :androidApp:assembleDebug :shared:jvmTest :androidApp:lintDebug
```

터미널에서는 `JAVA_HOME`에 JBR 경로, `ANDROID_HOME`에 SDK 경로를 지정해야 한다.
개인 SDK 경로를 `local.properties`에 작성할 수도 있지만 Git에는 포함하지 않는다.
APK: `androidApp/build/outputs/apk/debug/androidApp-debug.apk`.

로그인 화면의 **계정 없이 데모 둘러보기**는 학교 로그인과 실제 AI 호출 없이
홈·공지·학사·AI 화면을 확인한다. 데모 자료는 명확히 표시하며 실제 응답과 섞지 않는다.

## 이 Mac의 KNU 서버 연결

1. [서버 개발 실행 안내](../../server/api/docs/dev-run.md)에 따라 API·DB·Redis·worker를 실행한다.
2. API 서버에서 Node.js 22+와 [대화 DB 마이그레이션](../../docs/chat-context.md)을 준비한다.
3. 에뮬레이터 기본 주소는 `http://10.0.2.2:8000`. 포트가 다르면 **서버 연결 설정**에서 변경한다.
4. 실제 Android 기기는 Mac의 사설 IP를 사용한다. 기기 접근을 허용하려면 API를
   `--host 0.0.0.0`으로 실행하고 같은 신뢰 가능한 LAN에서만 테스트한다.
5. 먼저 **서버 연결 테스트**를 누른다. 이 요청은 학번·비밀번호·JWT 없이
   `/api/health`만 확인한다. Android 17(API 37)에서는 로컬 서버 접속 전에
   **주변 기기** 권한을 허용해야 한다. 거부하거나 나중에 철회한 경우에는 앱에서
   안내하고 연결을 중단한다. 공개 인터넷 서버만 이용할 때는 이 권한을 요청하지 않는다.

Android 17의 [로컬 네트워크 권한 규칙](https://developer.android.com/privacy-and-security/local-network-permission)에
맞춰 manifest 선언과 런타임 요청을 모두 구현했다. 자동 로그인·새로고침·동기화 등
모든 API 전송에 동일한 사전 검사를 적용하며 비밀번호를 로그에 출력하지 않는다.

Debug 빌드만 로컬·사설 IP의 HTTP를 허용한다. 배포 빌드는 HTTPS만 허용하며 최초
실행 시 서버 주소를 설정한다. HTTP는 포털 비밀번호 보호를 제공하지 않으므로 외부
네트워크에서 사용하지 않는다. 서버 주소 변경은 기기 세션만 초기화하며 서버 기록은 남는다.

## 기능

- 공통 상단바·하단 탭 없이 화면 제목 옆 메뉴 버튼으로 여는 왼쪽 사이드바
- 사이드바 스와이프 열기/닫기, 바깥 영역 탭·Android 뒤로 가기로 닫기
- 포털 로그인, 홈 추천·마감 공지, 공지 카테고리·페이지 이동·원문 링크
- 학교/개인 모델 AI 대화, 서버 대화 목록·이어쓰기·새 대화·삭제
- 시간표, 취득학점, 성적 분포·누적 성적, 포털/LMS 재동기화
- LMS 강의·학습 항목, 완료 표시·관심 강의 필터·KNU 목록에서 삭제
- 관심사, 개인 AI API 키 연결·모델 선택, Codex 외부 인증 흐름
- 서버 주소 변경과 로그아웃

서버 원본과 실제 학교 데이터를 우선하며 시간표·성적이 없을 때 가짜 자료로 채우지 않는다.
LMS 완료 체크는 KNU의 관리 표시일 뿐 학교 과제 제출을 대신하지 않는다.

시간표는 월~금 주간 캘린더로 함께 표시하며 남은 화면 높이에 맞춰 한 주 전체가
들어오도록 교시 높이를 조절한다. 연속된 같은 과목·강의실의 수업은 한 블록으로
합치되, 빈 교시·강의실 변경·주야간 시간 간격은 유지한다. 주말 수업이 있으면
토/일 열도 포함한다. 수업을 누르면 원본 과목명·강의실·전체 시간을 확인할 수 있다.
과목명 기준의 색상은 새로고침해도 바뀌지 않는다.

AI 화면을 보는 동안 약 2초마다 대화 목록의 revision을 확인하고, 변경된 대화만
불러온다. 새로고침 로딩 표시나 기존 원문 비우기 없이 같은 화면에 반영하며 입력 중인
질문을 유지한다. 과거 메시지를 읽고 있을 때는 맨 아래로 강제 이동하지 않는다.
앱 복귀·AI 화면 진입 시 즉시 확인하고 백그라운드나 다른 화면에서는 polling을 중단한다.
최초 진입에서는 최신 대화를 열지만, 직접 **새 대화**를 선택하거나 질문을 작성 중일
때는 기존 대화로 임의 전환하지 않는다. 연결 실패 시 기존 대화를 유지하며 4~30초로
간격을 늘려 재시도한다. 저장되지 않은 답변이나 직접 전송 중인 내용을 덮어쓰지 않는다.

사이드바의 구성·닫기 동작은 Codmes Apple 클라이언트의 `RootView.swift`를 참고했다.
KNU는 Swift 코드를 복사하지 않고 Compose의 네이티브 drawer/gesture 처리를 사용한다.

기기에는 서버 주소와 Android Keystore로 암호화한 JWT만 저장한다. 비밀번호·개인 AI
API 키·대화 원문은 기기에 영구 저장하지 않는다. 대화는 본인 학번으로 KNU PostgreSQL에
보관되어 웹과 공유되며 Codmes 대화 DB와 별개다. **휴대폰에 Python·Java·PostgreSQL·Node를
설치할 필요는 없다.** 개발 PC의 JDK/SDK와 중앙 서버의 런타임은 별도다.

## 현재 검증 범위와 iOS

Android Debug APK·서명 없는 Release APK 빌드, 공통 Kotlin 테스트 21개,
Debug/Release Android lint와 에뮬레이터 데모 화면을 검증했다.
2026-10-07에는 Android 17 에뮬레이터에서 로컬 접속 권한 허용 → 연결 테스트 →
사용자가 직접 입력한 실제 포털 로그인까지 검증했다. 학교 제공 Ollama 모델
`gemma4:12b-mlx`로 두 번 대화한 뒤, 동일 계정의 웹에서 원본을 열고 이어서 질문해
앞서 전달한 테스트 코드를 정확히 답하는 것도 확인했다. 세 번의 질문·답변 원본 6개가
KNU PostgreSQL의 같은 대화에 저장됐다. 실제 시간표·취득학점·성적 데이터의 DB 저장도 확인했다.

이 짧은 실제 대화 시험은 기기 간 맥락 유지 검증이며 긴 대화 요약을 강제로 발생시킨
시험은 아니다. 요약 재사용·트랜잭션·충돌·재전송은 별도 일회용 PostgreSQL과 실제
Node 엔진, 모의 모델을 조합한 자동 테스트로 검증했다.
개인 유료 모델 호출·실기기 연결·모바일 배포 서명은 아직 검증하지 않았다.
Manager 0.2.3은 이후 이 Mac에서 설치·서버 시작·종료와 기존 데이터 유지까지 검증했다.

iOS 공통 코드 재사용을 위한 framework target은 `-PenableIos=true`로 켤 수 있지만,
**iOS 실행 앱·진입점·Keychain 저장소·Xcode 서명은 아직 구현하지 않았다.** 지금 완성한
실행 클라이언트는 Android이며 iOS 완성본이 있다는 뜻은 아니다.
