아래 문서는 지금까지 실제 리버스 엔지니어링으로 확인된 KNUIS Webcrea Dataset 구조 정리본이다.

KNUIS Webcrea Dataset Reverse Engineering 결과 정리

개요

초기에는 KNUIS 데이터를 HTML Table 파싱 방식으로 수집하였다.

HTML
↓
table
↓
tr
↓
td
↓
파싱

하지만 실제 분석 결과 KNUIS는 Webcrea Runtime 기반 시스템이며 대부분의 데이터가 HTML이 아닌 Dataset 객체에 저장되어 있었다.

따라서 앞으로의 데이터 수집 방식은 다음 구조를 따른다.

메뉴 실행
↓
iframe 진입
↓
Webcrea.GetObjectById()
↓
Dataset(G1~G4)
↓
arrData 추출
↓
JSON 저장

⸻

공통 데이터 추출 공식

const ds =
  frame.Webcrea.GetObjectById(
    "G1"
  );
ds.arrData

또는

JSON.stringify(
  ds.arrData
)

⸻

1. 시간표조회

메뉴

수업 · 수강
└─ 시간표조회

⸻

Dataset

G1

⸻

추출

frame.Webcrea
  .GetObjectById("G1")
  .arrData

⸻

확인된 컬럼

{
  LTTM_CD,
  MON,
  TUE,
  WED,
  THU,
  FRI,
  SAT
}

⸻

예시

MON[8]
=
"대학생활과미래설계..."

⸻

특징

기존 코드

parse_timetable_data()

는 HTML Table 파싱.

향후

G1.arrData

직접 사용 가능.

⸻

2. 나의 성적분포

메뉴

성적
└─ 나의성적분포

⸻

Frame

WHHSJV0275

⸻

Dataset

G1

⸻

추출

frame.Webcrea
  .GetObjectById("G1")
  .arrData

⸻

확인된 컬럼

년도
학기
학기명
년도학기
신청학점
취득학점
평점평균
합계평점
백분위평균점수
학년등수
학과등수
대학등수
학과평균
대학평균
학사경고

⸻

예시

{
  "년도학기":
  [
    "2022 1학기",
    "2022 2학기",
    "2025 1학기",
    "2025 2학기"
  ]
}

⸻

특징

현재

parse_grade_distribution()

에서 DOM Grid 파싱 수행 중.

향후

G1.arrData

직접 사용 가능.

⸻

3. 누적성적조회

메뉴

성적
└─ 누적성적조회(학부생)

⸻

Frame

WHHSJV0270

⸻

G1

의미

과목별 성적

⸻

추출

Webcrea
  .GetObjectById("G1")
  .arrData

⸻

주요 컬럼

SUBJ_CD
SUBJ_NM
GRD_CD
AVRP
SUM_SCR
POBT_FG_CD
POBT_FG_NM
LCTPT
TLSN_YYYY
TLSN_SHTM
RETLSN_YN

⸻

예시

SUBJ_NM
=
[
  "글쓰기기초",
  "선형대수",
  "C프로그래밍"
]

⸻

G2

의미

학기별 성적

⸻

추출

Webcrea
  .GetObjectById("G2")
  .arrData

⸻

주요 컬럼

YYYY
SHTM
ACQ_LCTPT
APLY_LCTPT
F_INC_AVRP_AVG
PCNT_AVG_SCR
SYEAR_RANK
BCH_WARN_YN

⸻

예시

{
  YYYY:
    ["2022","2022","2025","2025"],
  SHTM:
    ["1","2","1","2"]
}

⸻

G3

의미

이수구분별 학점 요약

⸻

추출

Webcrea
  .GetObjectById("G3")
  .arrData

⸻

주요 컬럼

POBT_FG_CD
ACQ_LCTPT
AVG_AVRP
SUM_AVRP
LCK_LCTPT

⸻

예시

전공필수
전공선택
교양필수
교양선택
일반선택

에 대한 집계 정보.

⸻

특징

현재

collect_webcrea_grid()

로 수집 중.

향후 Dataset 직접 사용 가능.

⸻

4. 졸업사전예고

메뉴

졸업
└─ 졸업사전예고

⸻

Frame

WHHJUV0910

⸻

Dataset

G4

⸻

확인 결과

G1 = 없음
G2 = 없음
G3 = 없음
G4 = 존재

⸻

추출

frame.Webcrea
  .GetObjectById("G4")
  .arrData

⸻

주요 컬럼

취득학점

BASIC_CUL_ESSEN
BASIC_CUL_CHOOSE
BAL_CUL_CHOOSE
ACCOM_CUL_ESSEN
ACCOM_CUL_CHOOSE
FUSION_RESER
COL
SUB_BGN
SUB_KEY
SUB_DEEP
TOT_SUM

⸻

졸업기준

SUST_BASIC_CUL_ESSEN
SUST_BASIC_CUL_CHOOSE
SUST_BAL_CUL_CHOOSE
SUST_SUB_BGN
SUST_SUB_KEY
SUST_TOT_SUM

⸻

예시

TOT_SUM
=
78
SUST_TOT_SUM
=
130

⸻

특징

기존

parse_graduation_data()

는 HTML Table 파싱.

실제 데이터는

G4.arrData

에 존재함.

⸻

최종 결론

현재 확인된 모든 주요 메뉴는 Webcrea Dataset 기반으로 동작한다.

시간표조회
→ G1
성적분포
→ G1
누적성적조회
→ G1
→ G2
→ G3
졸업사전예고
→ G4

⸻

리팩토링 방향

삭제 예정

parse_timetable_data()
_build_code_map()
parse_webcrea_grid()
collect_webcrea_grid()

⸻

공통 함수 도입

extract_arrdata(
    frame,
    dataset_id
)

⸻

목표 구조

메뉴 실행
↓
iframe 진입
↓
GetObjectById()
↓
arrData
↓
JSON 저장

HTML 파싱을 최소화하고 Webcrea Runtime을 직접 사용하는 방식으로 전환한다.