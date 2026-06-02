KNUIS Reverse Engineering & 디버깅 가이드 (실전 버전)

목표

우리가 최종적으로 만들고 싶은 건:

KNUIS 로그인
→ 시간표 자동 조회
→ 앱 내부 캐시 저장
→ Flutter UI 출력

시스템이다.

⸻

매우 중요한 전제

KNUIS는 일반 웹사이트가 아니다.

Webcrea 기반 런타임 웹앱

이다.

즉:

Page00
Webcrea
G1
arrData

같은 내부 JS 객체로 동작한다.

우리는:

HTML 파싱

이 아니라:

KNUIS 내부 JS 런타임 직접 호출

방식으로 데이터를 가져온다.

이걸 이해하지 못하면 디버깅 방향이 완전히 틀어진다.

⸻

전체 구조

현재 구조:

Flutter UI
↓
Hidden WebView
↓
KNUIS 내부 JS 실행
↓
dataset(arrData) 추출
↓
Dart 모델 변환
↓
FlutterSecureStorage 저장
↓
UI 출력

⸻

핵심 디버깅 원칙

KNUIS 디버깅의 핵심은:

현재 어떤 iframe 안에서
어떤 JS runtime이 살아있는가

를 확인하는 것이다.

즉:

iframe 구조 이해

가 가장 중요하다.

⸻

실제 디버깅 흐름

항상 아래 순서로 진행한다.

1. 현재 iframe 확인
2. 어떤 frame에 원하는 객체가 있는지 확인
3. menuId 확인
4. fn_runFileMDI 실행
5. iframe 생성 확인
6. Query 함수 확인
7. dataset(G1 등) 확인
8. arrData 추출
9. Flutter 저장 여부 확인
10. UI reload 확인

⸻

1단계 — iframe 구조 파악

가장 먼저 해야 하는 것:

Array.from(document.querySelectorAll("iframe"))
  .map(v => ({
    id: v.id,
    src: v.src,
  }));

이걸 반드시 실행한다.

왜냐하면:

KNUIS 대부분 기능은 iframe 내부 runtime

에서 동작하기 때문이다.

⸻

매우 중요

우리가 처음 계속 실패했던 이유:

main window에서 fn_runFileMDI 찾음

이었다.

하지만 실제로는:

LeftFrame.contentWindow

안에 존재했다.

즉:

Page00.funcLeft.fn_runFileMDI()

가 아니라:

let fn =
  document.querySelector("#LeftFrame")
    .contentWindow;
fn.Page00.funcLeft.fn_runFileMDI(
  "1000000062",
  0
);

가 정답이었다.

이건 매우 중요한 reverse engineering 포인트다.

⸻

2단계 — menuId 찾기

예:

시간표조회 → 1000000062

이 menuId는:

KNUIS 내부 프로그램 실행 ID

개념이다.

실행:

fn.Page00.funcLeft.fn_runFileMDI(
  "1000000062",
  0
);

⸻

3단계 — iframe 생성 확인

여기서 매우 중요.

fn_runFileMDI 호출 직후:

iframe이 바로 생성되지 않는다.

즉:

document.querySelector("#WHHSKV0580")

를 바로 실행하면:

null

이 나올 수 있다.

우리가 실제로 가장 오래 헤맸던 부분이 이것이다.

⸻

반드시 해야 하는 디버깅

Array.from(document.querySelectorAll("iframe"))
  .map(v => `${v.id} | ${v.src}`)
  .join("\n");

이걸 반복해서 실행한다.

그러면:

WHHSKV0580

iframe이 생성되는 순간을 확인 가능하다.

⸻

핵심 개념

fn_runFileMDI()
→ iframe 생성
→ iframe runtime 초기화
→ Query 함수 사용 가능

이다.

즉:

iframe 생성 대기

가 필수다.

⸻

4단계 — Query 함수 찾기

iframe 생성 후:

const frame =
  document.querySelector("#WHHSKV0580")
    .contentWindow;

존재하지 않으면 
Uncaught TypeError:
Cannot read properties of null
(reading 'contentWindow')
존재하면 undefine

이제 여기서:

Object.keys(frame.Page00)

실행.

그리고:

조회 버튼

관련 함수 탐색.

우리가 찾은 실제 함수:

Page00.F_TOPMENU.QueryG1()

이었다.

⸻

매우 중요

우리는:

HTML 버튼 클릭 자동화

를 한 것이 아니다.

실제로는:

KNUIS 내부 JS 함수 직접 호출

방식이었다.

즉:

Page00.F_TOPMENU.QueryG1()

를 직접 실행한 것이다.

이 차이는 매우 중요하다.

⸻

5단계 — dataset(G1) 찾기

이제:

const g1 =
  frame.Webcrea.GetObjectById("G1");

실행.

성공하면:

시간표 dataset 객체 확보 성공

이다.

⸻

6단계 — arrData 확인

이제:

Object.keys(g1.arrData)

실행.

결과:

[
  "LTTM_CD",
  "MON",
  "TUE",
  "WED",
  "THU",
  "FRI"
]

등 실제 dataset 구조 확인 가능.

⸻


KNUIS 데이터는 일반적으로
Dataset 객체(G1, G2 등)에 저장된다.

실제 데이터 저장 위치는
화면마다 다를 수 있으므로

Object.keys(dataset)

으로 구조를 먼저 확인한다.

시간표 화면의 경우에는

g1.arrData

에 실제 데이터가 저장되어 있었다.

즉 arrData는
시간표 화면에서 확인된 실제 필드이며,
모든 KNUIS 화면에서 보장되는 구조는 아니다.

⸻

7단계 — 실제 데이터 확인

예:

console.log(g1.arrData.MON)

결과:

대학생활과미래설계

같은 실제 시간표 데이터 확인 가능.

⸻

8단계 — Flutter에서 동일한 JS 실행

이제 브라우저 콘솔이 아니라:

controller.runJavaScript(...)

로 동일한 JS를 실행한다.

예:

await controller.runJavaScript(
  '''
const fn =
  document.querySelector("#LeftFrame")
    .contentWindow;
fn.Page00.funcLeft.fn_runFileMDI(
  "1000000062",
  0
);
''',
);

⸻

매우 중요

여기서도:

iframe 생성 대기

가 반드시 필요하다.

즉:

await Future.delayed(
  const Duration(seconds: 2),
);

같은 대기가 필요하다.

⸻

9단계 — Query 실행

이제:

await controller.runJavaScript(
  '''
const frame =
  document.querySelector("#WHHSKV0580")
    .contentWindow;
frame.Page00.F_TOPMENU.QueryG1();
''',
);

실행.

즉:

KNUIS 내부 조회 함수 직접 호출

이다.

⸻

10단계 — arrData 가져오기

예:

final raw =
  await controller
      .runJavaScriptReturningResult(
  '''
(() => {
  const frame =
    document.querySelector("#WHHSKV0580")
      .contentWindow;
  const g1 =
    frame.Webcrea.GetObjectById("G1");
  return JSON.stringify(
    g1.arrData,
  );
})();
''',
);

그러면:

시간표 JSON 문자열

을 Flutter로 반환 가능.

⸻

11단계 — Dart 모델 변환

이제:

arrData 구조
→ Dart 모델 구조

로 변환.

예:

class TimetableData {
  final Map<String, List<String>>
      dayData;
  const TimetableData({
    required this.dayData,
  });
}






iframe 구조 확인
→ menuId 확인
→ fn_runFileMDI 실행
→ iframe 생성 확인
→ Query 함수 찾기
→ dataset(G1 등) 찾기
→ arrData 분석
