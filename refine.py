from typing import List, cast
from langchain_core.messages import SystemMessage, HumanMessage
from model import get_model
from schema import MetadataSchema
from dotenv import load_dotenv


SYSTEM_PROMPT = """너는 공주대학교 공지사항을 구조화된 메타데이터로 변환하는 분석가다.

원칙:
- 본문에 명시된 사실만 사용한다. 추측·창작·일반 상식 추가 금지.
- 입력에 없는 정보는 null 또는 기본값으로 처리한다.
- 모든 출력은 한국어로 작성한다."""


def _user_prompt(item: dict) -> str:
    return f"""다음 공주대 공지를 분석해서 스키마에 맞게 추출해라.

# 입력
- 제목: {item['title']}
- 등록일: {item['date']}
- URL: {item['url']}
- 본문:
{item['content']}

# 필드별 규칙

## title
- 입력 제목을 그대로 사용한다 (앞뒤 공백·이상한 줄바꿈만 정리).

## content
- 본문의 핵심을 1~2문장, 120자 이내로 요약한다.
- "누가, 무엇을, 언제(있다면)" 중심으로 작성.
- 본문 단순 복사 금지.
- 본문이 "내용을 찾을 수 없음"이거나 비어있으면 제목을 그대로 사용한다.

## target
- 본문에 **명시된** 대상 학과/학부명만 정확히 추출 (약어 X, 풀네임).
- 전교생/재학생/학년 단위 대상은 ["전체"].
- 단과대 단위면 단과대명 그대로 (예: ["공과대학"]).
- 여러 학과면 모두 나열 (예: ["컴퓨터공학과", "소프트웨어학과"]).
- 명확하지 않으면 ["전체"].

## deadline
- **신청/접수/모집 기간**만 추출한다 (행사 진행일, 등록일은 제외).
- 형식: "yyyy-mm-dd ~ yyyy-mm-dd" (단일 날짜면 "yyyy-mm-dd").
- 본문에 없거나 모호하면 null.

## category
- 다음 중 정확히 하나만 선택: 수강신청, 장학, 대회, 어학연수, 학점교류, 공모전, 교내행사, 학사, 취업, 모집, 기타.

## url
- 입력 URL을 그대로 복사한다 (수정·생성 금지).

# 예시
입력:
  제목: "[장학] 2026 1학기 가계곤란 장학금 신청 안내"
  등록일: "2026-04-15"
  URL: "https://www.kongju.ac.kr/.../12345"
  본문: "공주대학교 재학생 중 가계곤란 학생을 대상으로 장학금을 신청받습니다. 신청기간: 2026-05-01 ~ 2026-05-15."

출력:
  title: "[장학] 2026 1학기 가계곤란 장학금 신청 안내"
  content: "공주대 재학생 중 가계곤란 학생 대상 1학기 장학금 신청 접수."
  target: ["전체"]
  deadline: "2026-05-01 ~ 2026-05-15"
  category: "장학"
  url: "https://www.kongju.ac.kr/.../12345"
"""


def refine(crawled_data: List[dict]) -> List[MetadataSchema]:
    load_dotenv()
    model = get_model().with_structured_output(MetadataSchema)
    system_msg = SystemMessage(content=SYSTEM_PROMPT)

    refined: List[MetadataSchema] = []
    for item in crawled_data:
        result = cast(
            MetadataSchema,
            model.invoke([system_msg, HumanMessage(content=_user_prompt(item))]),
        )
        refined.append(result)
    return refined