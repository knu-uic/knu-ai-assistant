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
- 등록일: {item['date']}
- URL: {item['url']}
- 본문:
{item['content']}

# 필드별 규칙

## title
- 입력 제목을 그대로 사용한다 (앞뒤 공백·이상한 줄바꿈만 정리).

## content
- 본문의 핵심을 한 문단으로 요약한다

## target
- 본문 내용을 토대로 어떤 학과의 학생 또는 어떤것에 관심이 있는 학생이 참여하면 좋을지 기재

## deadline
- **신청/접수/모집 기간**만 추출한다 (행사 진행일, 등록일은 제외).
- 형식: "yyyy-mm-dd ~ yyyy-mm-dd" (단일 날짜면 "yyyy-mm-dd").
- 본문에 없거나 모호하면 null(수정, 생성 금지).

## category
- 본문 내용을 토대로 카테고리를 선정

## url
- 입력 URL을 그대로 복사한다 (수정·생성 금지).
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