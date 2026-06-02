# KNUIS(Webcrea) Reverse Engineering & Playwright 데이터 추출 가이드

## 목표

최종 목표는 다음과 같다.

text Playwright 로그인 ↓ KNUIS 메뉴 실행 ↓ 조회 함수 실행 ↓ Webcrea Dataset 획득 ↓ arrData 추출 ↓ JSON 변환 ↓ DB 저장 

우리는 HTML을 파싱하지 않는다.

대신 KNUIS 내부 JavaScript Runtime(Webcrea)을 직접 호출하여 데이터를 가져온다.

---

# 1. KNUIS 구조 이해

## 일반 웹사이트

일반적인 웹사이트는 보통 다음과 같이 동작한다.

text HTML ↓ 테이블 ↓ BeautifulSoup ↓ 데이터 추출 

---

## KNUIS

KNUIS는 다르다.

text Webcrea Runtime ↓ Dataset(G1) ↓ arrData ↓ 화면 렌더링 

즉 화면은 단순 출력 결과일 뿐이다.

실제 데이터는 Dataset 안에 있다.

---

# 2. 가장 중요한 개념

## iframe

KNUIS 대부분 기능은 iframe 내부에서 동작한다.

예:

text Top Window ├─ LeftFrame ├─ MainFrame └─ WHHSKV0580 

따라서 항상 먼저 iframe 구조를 확인해야 한다.

---

# 3. iframe 구조 확인

콘솔에서:

javascript Array.from(document.querySelectorAll("iframe"))   .map(v => ({     id: v.id,     src: v.src,   })); 

실행.

결과:

javascript [   {     id: "LeftFrame",     src: "..."   },   {     id: "WHHSKV0580",     src: "..."   } ] 

---

# 4. 메뉴 실행 함수 찾기

처음에는 다음 코드가 실패했다.

javascript Page00.funcLeft.fn_runFileMDI(   "1000000062",   0 ); 

이유:

Page00은 Top Window에 없었다.

---

실제로는 LeftFrame 안에 있었다.

정답:

javascript document   .querySelector("#LeftFrame")   .contentWindow   .Page00   .funcLeft   .fn_runFileMDI(     "1000000062",     0   ); 

---

# 5. menuId 찾기

가장 쉬운 방법:

fn_runFileMDI 후킹

javascript const left =   document.querySelector("#LeftFrame")     .contentWindow;  const original =   left.Page00.funcLeft.fn_runFileMDI;  left.Page00.funcLeft.fn_runFileMDI = function(menuId,arg){    console.log(     "MENU:",     menuId   );    return original.apply(     this,     arguments   ); }; 

이후 메뉴 클릭.

콘솔:

text MENU: 1000000062 

---

# 6. 메뉴 실행 후 iframe 찾기

메뉴 실행:

javascript left.Page00.funcLeft.fn_runFileMDI(   "1000000062",   0 ); 

---

새 iframe 생성 확인:

javascript Array.from(   document.querySelectorAll("iframe") ) .map(v =>   `${v.id} | ${v.src}` ) .join("\n"); 

---

예:

text WHHSKV0580 

생성 확인.

---

# 7. Runtime 진입

javascript const frame =   document     .querySelector("#WHHSKV0580")     .contentWindow; 

---

현재 Runtime 확인:

javascript Object.keys(frame)   .filter(     k => k.startsWith("Page")   ); 

결과:

javascript [   "PageObject",   "Page00" ] 

---

# 8. Page00 구조 분석

javascript Object.keys(frame.Page00) 

시간표 예:

javascript [   "F_TOPMENU",   "G1",   "funcMain" ] 

개설강좌조회 예:

javascript [   "F1",   "F2",   "F_TOPMENU",   "G1",   "funcMain" ] 

---

# 9. 조회 함수 찾기

시간표 화면

javascript Object.keys(   frame.Page00.F_TOPMENU ); 

결과:

javascript [   "QueryG1" ] 

---

조회 실행:

javascript frame.Page00   .F_TOPMENU   .QueryG1(); 

---

# 10. 개설강좌조회 화면

동일하게 탐색.

javascript Object.keys(   frame.Page00.F_TOPMENU ); 

결과:

javascript [   "BTN_SRCH",   "BTN_XLS" ] 

함수 없음.

---

BTN_SRCH 확인.

javascript frame.Page00   .F_TOPMENU   .BTN_SRCH 

결과:

javascript {   OnCLICK: f() } 

---

# 11. 클릭 이벤트 분석

javascript frame.Page00   .F_TOPMENU   .BTN_SRCH   .OnCLICK   .toString(); 

결과:

javascript function(currNode,currObj){   let ret =     FuncPage00_F_TOPMENU_BTN_SRCH_OnCLICK(       currNode,       currObj     );   return ret; } 

---

실제 함수 확인.

javascript frame  .FuncPage00_F_TOPMENU_BTN_SRCH_OnCLICK  .toString(); 

결과:

javascript function FuncPage00_F_TOPMENU_BTN_SRCH_OnCLICK(   currNode,   currObj ){   Webcrea.Refresh("G1"); } 

발견.

---

즉:

text 조회 버튼 ↓ Webcrea.Refresh("G1") ↓ G1 재조회 

구조.

---

# 12. G1 Dataset 찾기

Page00 내부 확인.

javascript Object.keys(   frame.Page00.G1 ); 

시간표:

javascript [   "MON",   "TUE",   "WED",   ... ] 

개설강좌조회:

javascript [   "SUBJ_CD",   "SUBJ_NM",   "KOR_NM",   ... ] 

---

# 13. 실제 Dataset 객체 찾기

javascript const g1 =   frame.Webcrea     .GetObjectById("G1"); 

---

확인:

javascript Object.keys(g1) 

결과:

239개 이상.

---

데이터 관련 속성 탐색.

javascript Object.keys(g1) .filter(   k =>     k.toLowerCase()       .includes("data") ); 

결과:

javascript [   "arrData",   "arrData_Org",   ... ] 

---

# 14. 실제 데이터 발견

javascript g1.arrData 

시간표 결과:

javascript {   LTTM_CD: [...],   MON: [...],   TUE: [...],   WED: [...],   THU: [...],   FRI: [...],   SAT: [...] } 

---

중요.

arrData는

javascript [   row1,   row2 ] 

형태가 아니라

javascript {   COLUMN: Array } 

형태였다.

---

# 15. 데이터 추출 공식

최종 공식:

javascript const g1 =   frame.Webcrea     .GetObjectById("G1");  return JSON.stringify(   g1.arrData ); 

---

# 16. Playwright 적용

조회 실행:

javascript await page.evaluate(() => {    const frame =     document       .querySelector("#WHHSKV0580")       .contentWindow;    frame.Webcrea.Refresh("G1");  }); 

---

조회 완료 대기.

javascript await page.waitForTimeout(2000); 

---

데이터 추출.

javascript const raw = await page.evaluate(() => {    const frame =     document       .querySelector("#WHHSKV0580")       .contentWindow;    const g1 =     frame.Webcrea       .GetObjectById("G1");    return JSON.stringify(     g1.arrData   );  }); 

---

Node.js

javascript const data =   JSON.parse(raw); 

---

# 최종 Reverse Engineering 패턴

새로운 메뉴를 분석할 때는 항상 아래 순서를 따른다.

text 1. 메뉴 실행 ↓ 2. iframe 찾기 ↓ 3. contentWindow 진입 ↓ 4. Page00 확인 ↓ 5. F_TOPMENU 분석 ↓ 6. 조회 함수 찾기 ↓ 7. 조회 실행 ↓ 8. G1 찾기 ↓ 9. Webcrea.GetObjectById("G1") ↓ 10. arrData 찾기 ↓ 11. JSON 추출 ↓ 12. Playwright 반환 

이 패턴은 시간표조회, 개설강좌조회뿐 아니라 대부분의 Webcrea 기반 KNUIS 메뉴에 동일하게 적용된다.