# KNUIS(Webcrea) 크롤링 기술 명세 가이드

공주대 통합정보시스템(KNUIS)은 **Webcrea** 프레임워크 기반 MDI(Multiple Document
Interface) 웹앱이다. 일반 HTML 크롤링이 통하지 않으며, 프레임워크 내부 JavaScript
런타임을 직접 호출/파싱해야 한다. 이 문서는 `knuis_sync.py` 구현에서 확립한 기법을
정리한다. 향후 동일 프레임워크(Webcrea 기반 타 대학 포털 포함) 크롤러 개발·유지보수 시 참고.

> 구현 기준 파일: `knuis_sync.py`, 소비처: `app_pages/portal.py`·`app_pages/home.py`, 저장: `db.py`

---

## 1. 왜 일반 크롤링이 안 되나 — 프레임워크 구조적 한계

| 항목 | 일반 웹 | KNUIS(Webcrea) |
|------|---------|----------------|
| 데이터 위치 | HTML `<table>` | JS 런타임 객체(`Webcrea.GetObjectById(gid).arrData`) |
| 화면 | 데이터 그 자체 | 런타임 데이터의 **렌더 결과**(부산물) |
| 메뉴 | `<a href>` 링크 | JS 함수 `fn_runFileMDI(menuId, 0)` 호출 |
| 그리드 렌더 | 전체 행 DOM | **가상화** — 보이는 행만 DOM에 존재 |
| 프레임 | 단일 문서 | 다중 중첩 iframe(shell + 데이터 프레임 + 팝업) |
| 셀 값 | 텍스트 | 코드값(`C2A090`) + 별도 디코드 테이블 |

핵심 결론 3가지:
1. **메뉴는 클릭하지 말고 함수로 직접 실행한다.** (가상화 메뉴 트리 스크롤·매칭은 느리고 불안정)
2. **데이터는 DOM이 아니라 arrData(런타임 객체)에서 읽는다.** (가상화 행 누락 면역)
3. **프레임은 URL만으로 고르지 말고 "데이터가 실제 적재됐는지"로 고른다.**

---

## 2. 진입 아키텍처 — 로그인 → MDI 화면 진입

```
Playwright 로그인(portal.kongju.ac.kr)
  ↓ reload (포털 구조상 필수)
"통합정보시스템" 버튼 클릭 → 새 탭(KNUIS MDI shell)
  ↓
LeftFrame.Page00.funcLeft.fn_runFileMDI(menuId, 0)  ← 화면 직접 진입
  ↓ crossurl.jsp 자동 호출로 데이터 적재
WHHxxxx 프레임의 Webcrea 런타임에 arrData 채워짐
```

### 2.1 MDI API 직접 실행 원리

KNUIS 좌측 메뉴 클릭은 내부적으로 `fn_runFileMDI(menuId, 0)`를 호출해 해당 업무
화면(MDI 탭)을 연다. 메뉴를 화면에서 찾아 클릭하는 대신 이 함수를 직접 호출하면:
- 메뉴 항목 로드(최대 2분) 대기 불필요
- 가상화 트리 스크롤·라이브값 매칭(flaky) 불필요
- menuId만 알면 즉시 진입

**menuId 수집법** — 로그인 직후 top 콘솔에서 `fn_runFileMDI`를 후킹하고 메뉴를 한 번씩
수동 클릭하면 콘솔에 찍힌다:

```javascript
// top 프레임 콘솔. 좌측 메뉴 클릭하기 전에 1회 실행.
(function () {
  const L = document.querySelector('#LeftFrame').contentWindow;
  const orig = L.Page00.funcLeft.fn_runFileMDI;
  L.Page00.funcLeft.fn_runFileMDI = function (...a) {
    console.log('MENU menuId =', JSON.stringify(a));
    return orig.apply(this, a);
  };
})();
```

확정된 menuId(공주대 학부생 기준):

| 화면 | menuId | 데이터 프레임 URL 키 |
|------|--------|---------------------|
| 시간표조회 | `1000000062` | `WHHSKV` |
| 나의성적분포 | `1000000103` | `WHHSJV0275` |
| 누적성적조회 | `1000000102` | `WHHSJV0270` |
| 졸업사전예고 | `1000000111` | `WHHJUV` (+ 안내문 팝업 `WHHJUV0942`) |

### 2.2 프레임 핸들 함정 — 매 시도 top에서 재진입

`open_menu()` (knuis_sync.py)는 Playwright `page.frame(name="LeftFrame")` 핸들을
**잡아두지 않는다.** 통합정보시스템 진입 직후 LeftFrame은 여러 번 리로드되는데, 잡아둔
프레임 핸들은 `execution context destroyed`로 죽어 `evaluate`가 계속 실패한다(첫 진입만
120초 헛돔). 대신 **top 페이지에서 매 시도마다 `querySelector('#LeftFrame').contentWindow`로
살아있는 프레임을 새로 잡는다.**

```python
def open_menu(page, menu_id, timeout_sec=120) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            ok = page.evaluate("""(id) => {
                const w = document.querySelector('#LeftFrame')?.contentWindow;
                if (w && w.Page00 && w.Page00.funcLeft && w.Page00.funcLeft.fn_runFileMDI) {
                    w.Page00.funcLeft.fn_runFileMDI(id, 0);
                    return true;
                }
                return false;
            }""", menu_id)
            if ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False
```

> 핵심: 함수가 **정의되는 즉시** 호출하므로 메뉴 항목이 다 채워질 때까지 기다리지 않는다.
> 첫 호출만 부팅 대기, 이후 화면은 즉시 반환.

---

## 3. 데이터 추출 — arrData 직접 파싱

### 3.1 arrData 구조

각 그리드/폼은 Webcrea 런타임 객체이고, 데이터는 **컬럼지향**으로 들어있다:

```javascript
Webcrea.GetObjectById("G1").arrData
// = { 컬럼A: [v0, v1, ...], 컬럼B: [v0, v1, ...], ... }   ← 행지향 아님!
```

주의: arrData는 일반 배열이 아니라 Webcrea 커스텀 객체일 수 있어 `.slice`/`.map`이
안 먹을 수 있다. `Object.keys`로 컬럼을 얻고 인덱스로 접근한다. `_my_data_seq_` 컬럼은 제외.

### 3.2 추출 헬퍼

```python
def get_arrdata(frame, grid_id) -> dict | None:
    """Webcrea.GetObjectById(gid).arrData를 컬럼지향 dict로 반환. 없으면 None."""
    return frame.evaluate("""(gid) => {
        if (!window.Webcrea) return null;
        let o; try { o = Webcrea.GetObjectById(gid); } catch (e) { return null; }
        if (!o || !o.arrData) return null;
        const out = {};
        for (const k of Object.keys(o.arrData)) {
            if (k === '_my_data_seq_') continue;
            out[k] = o.arrData[k];
        }
        return out;
    }""", grid_id)
```

이후 Python에서 컬럼지향 → 행지향 전치(`_build_grid`), 셀 접근(`_av`).

### 3.3 DOM 파싱 대비 이점

- **가상화 면역** — DOM은 보이는 행만 렌더되어 휠 스크롤로 누적 수집해야 했으나(폐기한
  `collect_webcrea_grid`), arrData는 전체 행을 한 번에 보장.
- **정확도** — 졸업 G4는 DOM에선 탭/개행 텍스트라 split이 취약했고 **위치 정렬까지
  어긋났다**(`SUST_FUSION_RESER="1~7"`이 DOM 렌더에선 교직 칸으로 밀림). arrData는 컬럼명이
  명시적이라 이 정렬 오류를 원천 차단.
- **숨은 데이터** — 포털 화면엔 없는 컬럼(예: 누적성적 결석 `ABSN_FRQ`)도 arrData엔 있어
  앱에서 추가 노출 가능.

---

## 4. 다중 프레임 식별 + 비동기 대기(폴링)

### 4.1 문제: URL만으로 프레임을 고르면 안 된다

졸업사전예고는 프레임이 여러 겹이다:
- **shell 프레임** — `#G4` HTML 칸은 있으나 Webcrea 런타임 없음
- **데이터 프레임**(HtmlAddrFrame) — Webcrea + arrData 실제 보유
- **안내문 팝업**(`WHHJUV0942`) — 모달, 데이터 무관

`"WHHJUV" in url and frame.query_selector("#G4")`로 고르면 **shell을 집어** `get_arrdata`가
None을 반환한다(`학적 정보를 찾지 못했습니다` 에러의 실제 원인).

### 4.2 해결: "데이터 적재됨"을 판정 기준으로

DOM 존재 여부 대신 **`get_arrdata(frame, "G4")`가 truthy인지**로 프레임을 고른다.
이 한 조건이 두 문제를 동시 해결:
- `get_arrdata`는 Webcrea 런타임이 있어야 값 반환 → shell 프레임 자동 탈락
- arrData가 채워졌을 때만 truthy → 데이터 로드 전 통과 안 함(비동기 대기 겸용)

```python
data_frame = None
deadline = time.time() + 20
while time.time() < deadline and data_frame is None:
    for p_item in context.pages:
        for frame in p_item.frames:
            try:
                if "WHHJUV" in frame.url and get_arrdata(frame, "G4"):
                    data_frame = frame
                    break
            except Exception:
                continue
        if data_frame:
            break
    if data_frame is None:
        time.sleep(0.5)
```

### 4.3 그리드 로드 대기 패턴

진입 직후 crossurl.jsp 응답 전에 파싱하면 빈 데이터를 긁는다. `wait_for_grid_rows`로
`tr[id="<gid>.Data0"]` DOM 행이 렌더될 때까지 폴링한 뒤 arrData를 읽는다(DOM 렌더 ≈ arrData
적재 신호).

> 폴링 일반 원칙: **"무엇이 준비되면 진행할지"를 명확한 조건으로 표현**하고, deadline까지
> 짧은 간격(0.5s)으로 재확인. 고정 sleep은 느리고 불안정.

---

## 5. 하이브리드 한글 디코딩 (_NM 우선 + code_map 보충)

Webcrea 그리드 셀은 코드값을 담고 화면 표시값은 별도다. 두 경로가 있다:

1. **_NM 한글짝** — arrData에 코드 컬럼 옆 한글 컬럼이 동봉된 경우. 예: 누적성적 G1의
   `POBT_FG_CD`(C27010) ↔ `POBT_FG_NM`(교양필수), `SUBJ_CD` ↔ `SUBJ_NM`. → **_NM을 그대로 사용**.
2. **code_map 디코딩** — _NM 짝이 없는 코드. 예: 등급 `GRD_CD`(C2A090→F), 이수구분
   `POBT_FG_CD`(G3, _NM 없음). → 화면의 셀렉트박스 항목에서 코드→라벨 맵을 만들어 디코딩.

```python
def _build_code_map(frame) -> dict:
    return frame.evaluate("""() => {
        const m = {};
        document.querySelectorAll('li[role="selectboxitem"]').forEach(li => {
            const c = li.getAttribute('code');
            if (c) m[c] = (li.getAttribute('svalue') || li.innerText || '').trim();
        });
        return m;
    }""")
```

**전략: _NM 우선, 없으면 code_map.** _NM은 항상 채워져 있어 셀렉트박스 로드 타이밍에
의존하지 않으므로 더 안전하다. code_map은 최소한으로만 사용.

그리드 스펙은 `(표시라벨, arrData컬럼, is_code)` 리스트로 선언하고 `_build_grid`가
일괄 처리(`is_code`면 code_map 디코딩):

```python
CUMULATIVE_G1_SPEC = [
    ("이수구분", "POBT_FG_NM", False),  # _NM 직접
    ("등급", "GRD_CD", True),           # code_map 디코딩
    ...
]
```

---

## 6. 출력 계약 보존 원칙

추출 방식(DOM→arrData)을 바꿔도 **파서 반환 shape은 100% 유지**해 소비처를 무수정으로
두는 것이 핵심 전략이었다.

| 파서 | 반환 | 소비처 계약 |
|------|------|------------|
| `parse_timetable_data` | `[{frame_url, frame_name, rows}]` | home.py: `rows[0]`에 "요일/교시", 셀 정규식 `(.+)\((\d+)\s+([^)]+)\)\s*(.*)` |
| `parse_grade_distribution` | `{frame_url, grids:{G1:{title,columns,rows}}, summary:[[라벨,값]]}` | portal.py 표 렌더 |
| `parse_cumulative_grades` | `{frame_url, grids:{G1,G2,G3}}` | portal.py 표 렌더 |
| `parse_graduation_data` | `(name, major, year, grad_json)` | portal.py `cols_def` ↔ grad_json 중첩 경로 1:1 |

표 구조를 바꿔야 할 땐(졸업 표 레이아웃 정정처럼) **소비처(portal.py cols_def·헤더)와
파서(grad_json 키)를 함께** 바꿔 1:1 대응을 유지한다.

### 시간표 셀 주의
시간표 G1 arrData의 `MON~SAT` 값에 "과목명(분반 교수) 강의실"이 모두 들어있고
`*_SUST` 컬럼은 강의코드(C4T010)라 표시에 불필요 → 무시. `LTTM_CD`의 `<br>`는 공백 정규화
(home.py가 `split(" ")[0]`로 교시명 추출하므로 개행이 아닌 공백이어야 함).

---

## 7. 문제 해결 케이스 모음

### Case 1 — `fn_runFileMDI` 첫 호출 120초 헛돎 → 시간표 누락
- **증상**: step3(첫 진입)만 `fn_runFileMDI 준비 못함`, step4+는 즉시 성공.
- **원인**: 잡아둔 LeftFrame 핸들이 진입 직후 리로드로 `context destroyed`.
- **해결**: top에서 매 시도 `#LeftFrame.contentWindow` 재진입(§2.2).

### Case 2 — 졸업 `학적 정보(F_SRCH arrData)를 찾지 못함`
- **증상**: 졸업만 실패, name/major=None.
- **원인**: `#G4` DOM이 shell 프레임에도 있어 런타임 없는 프레임을 집음 + 데이터 적재 전 읽음.
- **해결**: 프레임 판정 기준을 `get_arrdata(frame,"G4")` truthy로 변경(§4.2).

### Case 3 — 누적성적에 '결석' 컬럼이 포털엔 없음
- **판단**: arrData `ABSN_FRQ`는 포털 화면엔 숨겨졌지만 유용 → **의도적으로 추가 노출**(이점).

### Case 4 — 졸업 취득학점 표가 포털과 다른 구조
- **증상**: 교직이 자과/타과 2칸, 콜라주가 기초/필수(실제 포털은 교직 단일, 콜라주 자과/타과,
  복수전공 기초/필수/선택).
- **원인**: portal.py 하드코딩 헤더가 실제 포털 레이아웃과 불일치(arrData 전환 이전부터 존재).
- **해결**: 실제 포털 화면과 arrData 컬럼 대조로 매핑 확정 후 portal.py 헤더·cols_def +
  knuis grad_json을 함께 수정.
  - 교직 = `PRO`(SUST_PRO/PRO), 컬럼 순서상 전공계와 융합탐색 사이 = 교직 위치로 확인
  - 콜라주 자과/타과 = 기준 `A_COL_SELF`/`A_COL_OTHER`, 취득 `COL_SELF`/`COL_OTHER`
  - 복수전공 기초 = `DOU_BGN_LCTPT`/`DOU_SUB_BGN`
- **교훈**: 코드명만으로 모호한 컬럼은 **실제 포털 화면의 값과 1:1 대조**해 확정한다.

### Case 5 — `_m`/`["_","m"]`처럼 글자가 쪼개져 덤프됨
- **원인**: arrData가 아닌 엉뚱한 메타 속성을 문자열로 순회.
- **해결**: 데이터는 `o.arrData`에만 있음. 객체 속성 추측 금지, arrData 직접 접근(§3).

---

## 8. 신규 Webcrea 화면 분석 절차(체크리스트)

1. top 콘솔에서 `fn_runFileMDI` 후킹 → 메뉴 클릭으로 **menuId** 확보(§2.1)
2. 진입 후 콘솔 컨텍스트를 **해당 WHH 프레임**으로 변경
3. `Webcrea.GetObjectById(gid).arrData`로 그리드/폼 ID(`G1`,`G2`,`F1`,`F_SRCH`,`G4`...)와
   **컬럼 키·첫 행 값** 덤프
4. 컬럼별로 **_NM 한글짝 유무** 확인 → 디코딩 전략 결정(§5)
5. 코드명이 모호한 컬럼은 **실제 포털 화면 값과 대조**해 의미 확정(§7 Case4)
6. 파서를 `(표시라벨, arrData컬럼, is_code)` 스펙으로 선언, 출력 shape은 소비처 계약에 맞춤(§6)
7. 프레임 선택은 `get_arrdata` truthy 기준 + 폴링 대기(§4)

### arrData 컬럼 덤프 스크립트(콘솔, 해당 WHH 프레임)
```javascript
(function () {
  if (!window.Webcrea) { console.warn('Webcrea 없음 — 프레임 확인'); return; }
  const cand = window.Page00 ? Object.keys(Page00) : ['G1','G2','G3','G4','F1','F_SRCH'];
  cand.forEach(id => {
    let o; try { o = Webcrea.GetObjectById(id); } catch (e) { return; }
    if (!o || !o.arrData) return;
    const cols = Object.keys(o.arrData).filter(c => c !== '_my_data_seq_');
    const row0 = {}; cols.forEach(c => row0[c] = o.arrData[c]?.[0]);
    console.log(`[${id}] 행수=${o.arrData[cols[0]]?.length ?? 0}, 컬럼=${cols.length}`);
    console.log('  컬럼:', cols);
    console.log('  row0:', JSON.stringify(row0));
    const code = cols.filter(c => /_CD$|_FG$/.test(c));
    const nm = cols.filter(c => /_NM$/.test(c));
    if (code.length) console.log('  코드컬럼:', code, '| _NM짝:', nm);
  });
})();
```

---

## 9. 정보 수집용 콘솔 스크립트 모음

신규 화면 역분석 시 실제로 사용한 콘솔 스크립트들. 브라우저 개발자도구(F12) 콘솔에 붙여넣어
실행한다. **콘솔 컨텍스트(상단 프레임 드롭다운)를 어디로 둘지가 중요**하므로 각 스크립트에 명시.

### 9.1 menuId 후킹 (콘솔 = top 프레임)

로그인 직후, 좌측 메뉴를 **클릭하기 전에** 1회 실행. 이후 메뉴를 클릭하면 menuId가 찍힌다.

```javascript
// [A] 콘솔 컨텍스트 = top. 좌측 메뉴 클릭 전에 실행.
(function () {
  const L = document.querySelector('#LeftFrame')?.contentWindow;
  const fn = L?.Page00?.funcLeft?.fn_runFileMDI;
  if (!fn) { console.error('fn_runFileMDI 없음. 포털 메인 화면 확인.'); return; }
  L.Page00.funcLeft.fn_runFileMDI = function (...a) {
    console.log('%c▶ menuId =', 'background:#007acc;color:#fff;padding:2px 6px', JSON.stringify(a));
    return fn.apply(this, a);
  };
  console.log('✅ 후킹 완료. 분석할 화면들을 차례로 클릭 → menuId 수집.');
})();
```

### 9.2 네트워크 스니퍼 (콘솔 = 해당 WHH 프레임, 조회 전)

데이터가 어느 엔드포인트(crossurl.jsp)로 어떤 payload로 오고 응답이 어떤지 확인. 조회 버튼
**누르기 전에** 실행 → 그 다음 조회. (조회 함수 없는 화면은 진입 즉시 자동 호출됨)

```javascript
// [B] 콘솔 컨텍스트 = 해당 WHH 프레임. 조회 전에 실행.
(function () {
  if (window.__sniff) { console.log('이미 설치됨.'); return; }
  window.__sniff = true;
  const log = (tag, url, body, resp) => {
    console.log('%c[NET] ' + tag, 'color:#e91e63;font-weight:bold', url);
    if (body) console.log('  req:', typeof body === 'string' ? body.slice(0, 1500) : body);
    if (resp) console.log('  resp(앞2500):', String(resp).slice(0, 2500));
  };
  const OX = window.XMLHttpRequest;
  window.XMLHttpRequest = function () {
    const x = new OX(); let u = '';
    const o = x.open; x.open = function (m, url) { u = url; return o.apply(x, arguments); };
    const s = x.send; x.send = function (b) {
      x.addEventListener('load', () => log('XHR', u, b, x.responseText));
      return s.apply(x, arguments);
    };
    return x;
  };
  if (window.fetch) {
    const of = window.fetch;
    window.fetch = function (u, opt) {
      return of.apply(this, arguments).then(r => { r.clone().text().then(t => log('fetch', u, opt?.body, t)); return r; });
    };
  }
  console.log('✅ 네트워크 후킹 완료. 이제 조회 실행.');
})();
```

### 9.3 그리드/함수 진단 (콘솔 = 해당 WHH 프레임, 조회 후)

조회 트리거 함수 후보 + 그리드 ID 자동 발견 + Webcrea 객체 데이터 메서드 + DOM 샘플.
arrData를 알기 전 단계의 1차 정찰용.

```javascript
// [C] 콘솔 컨텍스트 = 해당 WHH 프레임. 조회 완료 후 실행.
(function () {
  // C1: 조회/초기화 트리거 함수 후보
  if (window.Page00) {
    const fns = Object.keys(Page00).filter(k => /query|search|init|load|retrieve|inq|fn_/i.test(k));
    console.log('%c[C1] 조회 트리거 함수 후보:', 'color:#ff9800;font-weight:bold', fns);
    if (Page00.F_TOPMENU) console.log('   F_TOPMENU 버튼:', Object.keys(Page00.F_TOPMENU));
  } else console.warn('[C1] Page00 없음 — 프레임 잘못 선택?');

  // C2: 그리드 ID 자동 발견 (DOM의 .Data/.Header tr에서)
  const gids = [...new Set([...document.querySelectorAll('tr[id*=".Data"],tr[id*=".Header"]')]
    .map(tr => tr.id.split('.')[0]))];
  console.log('%c[C2] 발견된 그리드 ID:', 'color:#9c27b0;font-weight:bold', gids);

  // C3: 그리드별 DOM 헤더/샘플 (코드 셀은 {code,text}로 노출)
  gids.forEach(gid => {
    const hTr = document.querySelector(`tr[id="${gid}.Header"]`);
    const cols = hTr ? [...hTr.querySelectorAll('td')].map(td => {
      const sp = td.querySelector('span'); return sp ? (sp.getAttribute('title') || sp.innerText).trim() : td.innerText.trim();
    }) : [];
    const trs = [...document.querySelectorAll(`tr[id^="${gid}.Data"]`)];
    const sample = trs.slice(0, 2).map(tr => [...tr.querySelectorAll('td')].map(td => {
      const c = td.querySelector('input[codeobj="code"]');
      if (c) return { code: c.getAttribute('code'), text: (td.getAttribute('value') || td.innerText).trim() };
      const v = td.getAttribute('value'); return (v != null ? v : td.innerText).trim();
    }));
    console.log(`   [${gid}] cols(${cols.length}):`, cols);
    console.log(`   [${gid}] DOM행수=${trs.length}, 샘플:`, JSON.stringify(sample));
  });
})();
```

> `DOM행수`는 가상화로 보이는 행만 셈(총 행보다 적을 수 있음). 그래서 최종적으로는 §9.4 arrData를 쓴다.

### 9.4 arrData 컬럼 덤프 (콘솔 = 해당 WHH 프레임) — 핵심

파서 매핑 작성의 최종 재료. 각 그리드/폼의 arrData 컬럼 키·첫 행 값·코드/한글짝을 덤프.
(§8 체크리스트의 스크립트와 동일)

```javascript
// [D] 콘솔 컨텍스트 = 해당 WHH 프레임. 진입+조회 완료 후 실행.
(function () {
  if (!window.Webcrea) { console.warn('Webcrea 없음 — 프레임 확인'); return; }
  const cand = window.Page00 ? Object.keys(Page00) : ['G1','G2','G3','G4','F1','F_SRCH'];
  cand.forEach(id => {
    let o; try { o = Webcrea.GetObjectById(id); } catch (e) { return; }
    if (!o || !o.arrData) return;
    const cols = Object.keys(o.arrData).filter(c => c !== '_my_data_seq_');
    const row0 = {}; cols.forEach(c => row0[c] = o.arrData[c]?.[0]);
    console.log(`%c[${id}] 행수=${o.arrData[cols[0]]?.length ?? 0}, 컬럼=${cols.length}`, 'color:#4CAF50;font-weight:bold');
    console.log('  컬럼:', cols);
    console.log('  row0:', JSON.stringify(row0));
    const code = cols.filter(c => /_CD$|_FG$/.test(c));
    const nm = cols.filter(c => /_NM$/.test(c));
    if (code.length) console.log('  ⚠️ 코드컬럼:', code, '| _NM짝:', nm);
  });
})();
```

### 수집 순서 요약

```
1. [A] top에서 menuId 후킹 → 4개 화면 클릭하며 menuId 수집
2. 화면별: 콘솔 컨텍스트를 WHH 프레임으로 변경
   2-1. [B] 네트워크 스니퍼 → 조회 → 엔드포인트/payload/응답 확인 (선택)
   2-2. [C] 그리드/함수 1차 정찰 (선택)
   2-3. [D] arrData 컬럼 덤프 → 파서 매핑 작성 (필수)
3. 코드명 모호 컬럼은 실제 포털 화면 값과 대조 (§7 Case4)
```

---

## 부록 — 주의/금지

- `page.frame(name=...)` 핸들을 장기 보관 금지(리로드 시 context destroyed). 매 시도 재획득.
- DOM `<table>` 브루트포스 금지(가상화 누락·오매칭). arrData 직접.
- 고정 `sleep`로 로드 대기 금지. "데이터 적재됨" 조건 폴링.
- 코드 컬럼을 _NM 무시하고 무조건 code_map 디코딩 금지(셀렉트박스 로드 타이밍 의존). _NM 우선.
- 비밀번호는 argv 노출 금지. `--password-stdin`로 stdin 전달.
