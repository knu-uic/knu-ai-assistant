from typing import List, cast
from langchain_core.messages import SystemMessage, HumanMessage
from model import get_model
from schema import MetadataSchema
from dotenv import load_dotenv


SYSTEM_PROMPT = """
너는 공주대학교 공지사항을 구조화된 메타데이터로 변환하는 분석가다.

원칙:
- 본문에 명시된 사실만 사용한다. 추측·창작·일반 상식 추가 금지.
- 입력에 없는 정보는 null 또는 기본값으로 처리한다.
- 모든 출력은 한국어로 작성한다.
"""


def _user_prompt(item: dict) -> str:
    return f"""
다음 공주대 공지를 분석해서 스키마에 맞게 추출해라.

# 입력
- 제목: {item['title']}
- URL: {item['url']}
- 본문:
{item['content']}

# 필드별 규칙
## target
- 본문에서 **학과명** 또는 **학년**만 추출한다. 그 외에는 절대 넣지 않는다.
- 학과/학년 제한이 본문에 명시되지 않았다면 **무조건 `["전체"]`**.

### 절대 target에 넣지 말 것 (이 조건들만 있으면 ["전체"]로 처리):
- 나이 (예: "19세~39세 청년", "만 35세 이하")
- 지역/거주 (예: "대구 거주자", "수도권 외 지역", "OO시 주민등록자")
- 직업/직장 상태 (예: "재직자", "구직자", "프리랜서")
- 관심사/취향 (예: "AI에 관심있는 사람", "창업에 관심있는 학생")
- 국적/성별/소득 등 그 밖의 인구통계 조건

### target에 넣어도 되는 것:
- 학과명 (예: "컴퓨터공학과", "전자공학과", "공과대학")
- 학년 (예: "1학년", "3학년", "신입생", "졸업예정자")
- 학적 상태 (예: "재학생", "휴학생") — 학교 단위로 명시된 경우만

### 예시
- 본문: "컴퓨터공학과 3학년 대상" → ["컴퓨터공학과", "3학년"]
- 본문: "19세~39세 대구 외 거주 청년" → ["전체"]   (학과/학년 제한 없음)
- 본문: "재직자 우대, 전 학년 누구나" → ["전체"]   (재직자는 제외, "전 학년"은 제한 없음)
- 본문: "공과대학 재학생 한정" → ["공과대학", "재학생"]

## category
- 다음 5가지 대분류 중 가장 적합한 **단 1개**만 무조건 선택한다.
  1. 장학/등록 (국가장학금, 등록금 납부 등)
  2. 학사/수업 (수강신청, 휴학, 졸업, 성적 등)
  3. 진로/취업 (채용, 인턴, 자격증, 취업특강 등)
  4. 행사/공모전 (대회, 해커톤, 동아리, 축제 등)
  5. 일반/기타 (분실물, 시설안내, 예비군 등 위 4개에 속하지 않는 모든 것)

## keywords
- 본문의 핵심 주제, 혜택, 다루는 기술 등 사용자가 관심 가질만한 해시태그 단어를 1~3개 추출한다.
- 예시: ["멘토링"], ["해외연수", "어학"], ["파이썬", "특강"]

## start_date / end_date
- 접수기간을 시작일(start_date)과 마감일(end_date)로 분리해서 각각 yyyy-mm-dd 형식으로 추출한다.
- "2026-04-15 ~ 2026-05-04" → start_date="2026-04-15", end_date="2026-05-04"
- 마감일만 있는 경우(예: "~ 2026-05-04", "5월 4일까지") → start_date=null, end_date="2026-05-04"
- 시작일만 있는 경우 → start_date만 채우고 end_date=null
- 본문에 날짜가 전혀 없으면 둘 다 null.
"""


def refine(crawled_data: List[dict]) -> List[MetadataSchema]:
    load_dotenv()
    model = get_model().with_structured_output(MetadataSchema)
    system_msg = SystemMessage(content=SYSTEM_PROMPT)

    refined: List[MetadataSchema] = []
    for item in crawled_data[:2]:
        result = cast(
            MetadataSchema,
            model.invoke([system_msg, HumanMessage(content=_user_prompt(item))]),
        )
        refined.append(result)
    return refined