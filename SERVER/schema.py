from pydantic import BaseModel, Field
from typing import Literal


class RefinementSchema(BaseModel):
    """LLM이 원문에서 새로 추출해야 하는 필드만 담는다.

    제목·원문·URL은 이미 crawler가 확보했으므로 모델이 다시 출력하게 하지
    않는다. 긴 공지에서 원문 복사만으로 출력 토큰 한도를 소진하는 문제를
    막고, refine 단계가 실제 메타데이터 추출에만 집중하도록 한다.
    """

    summary: str = Field(
        description=(
            "공지의 핵심 내용을 2~3문장으로 요약한다. "
            "대상, 기간, 장소, 신청/참여 방법, 혜택이 명시되어 있으면 포함하고 "
            "본문에 없는 사실은 추가하지 않는다."
        )
    )
    target: list[str] = Field(
        description=(
            "본문에 명시된 학년(1학년~4학년, 신입생, 졸업예정자 등) 또는 "
            "재적상태(재학생, 휴학생 등) 제한만 추출한다. "
            "학과/단과대/소속은 제외하고, 제한이 없으면 ['전체']"
        )
    )
    start_date: str | None = Field(
        description="접수 시작일 (yyyy-mm-dd 형식). 본문에 없으면 null"
    )
    end_date: str | None = Field(
        description="접수 마감일 (yyyy-mm-dd 형식). 본문에 없으면 null"
    )
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] = Field(
        description="글의 대분류 카테고리"
    )
    keywords: list[str] = Field(
        description="본문의 핵심 주제·혜택·기술·활동을 나타내는 키워드 1~3개"
    )


class MetadataSchema(BaseModel):
    title: str = Field(description='게시판 글 제목')
    content: str = Field(description='게시판 글의 본문 원본 텍스트 (요약/축약 금지, 입력 그대로)')
    summary: str = Field(
        description=(
            "공지의 핵심 내용을 2~3문장으로 요약한다. "
            "대상, 기간, 장소, 신청/참여 방법, 혜택이 명시되어 있으면 포함하고 "
            "본문에 없는 사실은 추가하지 않는다."
        )
    )
    
    # target은 crawler source의 학과 범위가 아니라, 본문에 명시된 학년/재적상태 제한만 담는다.
    target: list[str] = Field(
        description=(
            "본문에 명시된 학년(1학년~4학년, 신입생, 졸업예정자 등) 또는 "
            "재적상태(재학생, 휴학생 등) 제한만 추출한다. "
            "학과/단과대/소속은 source.department가 담당하므로 절대 포함하지 않는다. "
            "학년/재적상태 제한이 없으면 무조건 ['전체']. "
            "예: ['3학년', '재학생'], ['전체']"
        )
    )
    
    start_date: str | None = Field(
        description="접수 시작일 (yyyy-mm-dd 형식). 본문에 없으면 null"
    )
    end_date: str | None = Field(
        description="접수 마감일 (yyyy-mm-dd 형식). 본문에 없으면 null"
    )
    
    # [수정 2] 대학교의 모든 범주를 커버하는 '고정형 대분류' (DB의 게시판 탭 역할)
    category: Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"] = Field(description="글의 대분류 카테고리")
    
    # [수정 3] 유연성을 100% 보장하는 '개방형 키워드' 추가 (유사도 검색 및 해시태그 역할)
    keywords: list[str] = Field(
        description=(
            "본문의 핵심 주제·혜택·기술·활동을 나타내는 키워드 1~3개. "
            "예: ['해커톤', '인공지능', 'AWS']"
        )
    )
    
    # 원문 게시글 URL
    url: str = Field(description="게시글의 url")
