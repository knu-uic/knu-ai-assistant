# 공주대학교 KNUIS Playwright 로그인 구조 분석

## 목적

Flutter Hidden WebView에서 구현된 인증 흐름을 Playwright로 재현한다.

범위:

text Portal 접속 ↓ SSO 로그인 ↓ Portal Main ↓ iframe#startP ↓ frmsystem_s.imgsys1 클릭 ↓ Popup 생성 ↓ 기존 SSO Session 전달 ↓ KNUIS Session 생성 ↓ KNUIS Main 

본 문서는 KNUIS 진입 단계까지만 다룬다.

---

# 1. 실제 인증 구조

KNUIS는 독립 로그인 시스템이 아니다.

실제 인증 흐름:

text portal.kongju.ac.kr ↓ SSO 로그인 페이지 ↓ SSO 인증 ↓ SSO Session 생성 ↓ Portal Session 생성 ↓ Portal Main ↓ 통합정보시스템 ↓ 기존 SSO Session 전달 ↓ KNUIS Session 생성 ↓ KNUIS Main 

즉

text Portal 로그인 = SSO 로그인 

이다.

---

# 2. Flutter와 Playwright 차이

Flutter WebView는 모바일 User-Agent를 사용한다.

text Mozilla/5.0 (iPhone ...) 

따라서 Flutter에서는

text m_sso.jsp 

가 확인되었다.

하지만 Playwright Chromium은 데스크탑 브라우저이다.

따라서 실제 SSO URL은 다음 중 하나일 수 있다.

text sso.jsp login.jsp m_sso.jsp 기타 SSO URL 

Playwright에서는 최초 실행 시 반드시 확인한다.

python await page.goto(     "https://portal.kongju.ac.kr/" )  await page.wait_for_load_state()  print(page.url) 

---

# 3. 실제 로그인 셀렉터

Flutter 코드에서 확인된 셀렉터

## 아이디

css input[name="sg_uid"] 

대체

css #frmIlban\.sg_uid 

---

## 비밀번호

css input[name="sg_pwd"] 

대체

css #frmIlban\.sg_pwd 

---

## 로그인 버튼

css #frmIlban\.pb_i_login 

실제 ID

text frmIlban.pb_i_login 

---

# 4. Playwright 로그인

python await page.fill(     'input[name="sg_uid"]',     student_id )  await page.fill(     'input[name="sg_pwd"]',     password )  await page.click(     '#frmIlban\\.pb_i_login' ) 

---

# 5. Portal Main 진입 확인

로그인 성공 후 Portal Main으로 이동한다.

확인된 iframe

html <iframe id="startP"> 

대기

python await page.wait_for_selector(     "#startP" ) 

---

# 6. startP iframe 구조

text Portal Main │ └── iframe#startP         │         └── frmsystem_s.imgsys1 

접근

python frame_element = await page.wait_for_selector(     "#startP" )  start_frame = await frame_element.content_frame() 

---

# 7. 통합정보시스템 버튼

실제 버튼 ID

text frmsystem_s.imgsys1 

CSS Selector

css #frmsystem_s\.imgsys1 

Playwright

python await start_frame.wait_for_selector(     "#frmsystem_s\\.imgsys1" ) 

---

# 8. Popup 생성

통합정보시스템 버튼 클릭 시 새 창이 생성된다.

Playwright

python async with page.expect_popup() as popup_info:      await start_frame.click(         "#frmsystem_s\\.imgsys1"     )  knuis_page = await popup_info.value 

---

# 9. KNUIS Session 생성

중요

text 통합정보시스템 클릭 = 로그인 

이 아니다.

실제 구조

text 기존 SSO Session ↓ KNUIS 전달 ↓ KNUIS Session 생성 ↓ KNUIS Main 

즉

text Portal Session O SSO Session O KNUIS Session X 

상태에서

text Portal Session O SSO Session O KNUIS Session O 

상태로 변경된다.

---

# 10. KNUIS 성공 판단

확인된 도메인

text knuis-s.kongju.ac.kr 

확인된 URL 패턴

text index.jsp mainMenuS.html startS.html leftMenuS.html 

대기

python await knuis_page.wait_for_url(     "**knuis-s.kongju.ac.kr**" ) 

확인

python print(knuis_page.url) 

---

# 11. 최종 구조

text portal.kongju.ac.kr │ ├── SSO 로그인 페이지 │      │ │      ├── input[name="sg_uid"] │      ├── input[name="sg_pwd"] │      └── #frmIlban.pb_i_login │ └── Portal Main         │         └── iframe#startP                 │                 └── #frmsystem_s.imgsys1                         │                         ▼                      Popup                         │                         ▼               knuis-s.kongju.ac.kr                         │                         ▼                   KNUIS Main 

---

# 현재까지 확인된 확정 정보

| 항목 | 값 |
|------|------|
| 아이디 필드 | input[name="sg_uid"] |
| 비밀번호 필드 | input[name="sg_pwd"] |
| 로그인 버튼 | frmIlban.pb_i_login |
| Portal iframe | startP |
| 통합정보 버튼 | frmsystem_s.imgsys1 |
| KNUIS 도메인 | knuis-s.kongju.ac.kr |
| KNUIS 성공 URL | index.jsp, mainMenuS.html, startS.html, leftMenuS.html |
| KNUIS 진입 방식 | Popup Window |
| 인증 구조 | Portal 로그인 시 SSO 완료 |
| 통합정보 역할 | 기존 SSO Session을 이용한 KNUIS Session 생성 |

---

# 다음 단계

KNUIS Main 진입 후 분석 대상:

javascript Page00.funcLeft.fn_runFileMDI(...) 

목표:

text 시간표 메뉴 실행 ↓ 업무 iframe 생성 ↓ dataset(arrData) 추출 ↓ JSON 변환 ↓ Playwright 반환 