from typing import Literal

from pydantic import BaseModel, Field


NoticeCategory = Literal["장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)"]
NoticePeriodKind = Literal[
    "application",
    "document_submission",
    "result_announcement",
    "event",
    "registration",
    "payment",
    "other",
]
NoticeAudienceKind = Literal[
    "department",
    "grade",
    "enrollment_status",
    "eligibility",
]


class NoticePeriodSchema(BaseModel):
    kind: NoticePeriodKind = Field(description="일정의 의미")
    starts_on: str | None = Field(
        default=None,
        description="시작일 yyyy-mm-dd. 원문에 없으면 null",
    )
    ends_on: str | None = Field(
        default=None,
        description="종료일 yyyy-mm-dd. 원문에 없으면 null",
    )
    source_text: str = Field(description="이 일정을 추출한 원문 문장")
    confidence: float = Field(ge=0, le=1, description="추출 신뢰도")
    inferred_year: bool = Field(
        default=False,
        description="원문에 연도가 없어 게시연도로 보정해야 하면 true",
    )


class NoticeAudienceSchema(BaseModel):
    kind: NoticeAudienceKind = Field(description="대상 조건 종류")
    value: str = Field(description="정규화한 대상 조건")
    source_text: str = Field(description="대상 조건의 원문 근거")
    confidence: float = Field(ge=0, le=1, description="추출 신뢰도")


class NoticeApplicationSchema(BaseModel):
    method: str | None = Field(default=None, description="신청 방법")
    application_url: str | None = Field(default=None, description="신청 URL")
    required_documents: list[str] = Field(
        default_factory=list,
        description="명시된 제출서류",
    )
    contact: str | None = Field(default=None, description="문의처")
    location: str | None = Field(default=None, description="장소")
    benefit: str | None = Field(default=None, description="금액·혜택")
    evidence: dict[str, str] = Field(
        default_factory=dict,
        description="각 값의 원문 근거",
    )


class RefinementSchema(BaseModel):
    """LLM이 공지 원문에서 추출하는 v2 구조화 메타데이터."""

    summary: str = Field(
        description=(
            "공지의 핵심 내용을 2~3문장으로 요약한다. "
            "대상, 기간, 장소, 신청/참여 방법, 혜택이 명시되어 있으면 포함하고 "
            "본문에 없는 사실은 추가하지 않는다."
        )
    )
    category: NoticeCategory = Field(description="글의 대표 대분류 카테고리")
    topics: list[str] = Field(
        description="본문의 핵심 주제·제도·활동을 나타내는 복수 topic 1~5개"
    )
    series_key: str | None = Field(
        default=None,
        description="매년 반복되는 같은 계열 공지를 묶는 영문 kebab-case 식별자",
    )
    periods: list[NoticePeriodSchema] = Field(
        default_factory=list,
        description="신청·제출·발표·행사 등 의미별 일정",
    )
    audiences: list[NoticeAudienceSchema] = Field(
        default_factory=list,
        description="학과·학년·재적상태·기타 자격조건",
    )
    application: NoticeApplicationSchema = Field(
        default_factory=NoticeApplicationSchema,
        description="신청 방법·제출서류·문의처·혜택",
    )
    extraction_confidence: float = Field(
        ge=0,
        le=1,
        description="전체 구조화 결과의 신뢰도",
    )


class MetadataSchema(BaseModel):
    """수집 파이프라인이 저장 단계에 넘기는 정규화 공지."""

    title: str = Field(description="게시판 글 제목")
    content: str = Field(description="게시판 글 본문 원본")
    summary: str
    category: NoticeCategory
    topics: list[str] = Field(default_factory=list)
    series_key: str | None = None
    periods: list[NoticePeriodSchema] = Field(default_factory=list)
    audiences: list[NoticeAudienceSchema] = Field(default_factory=list)
    application: NoticeApplicationSchema = Field(default_factory=NoticeApplicationSchema)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)

    # v2 저장 전환 동안 기존 조회 계약을 유지하기 위해 구조화 필드에서 계산한다.
    target: list[str] = Field(default_factory=lambda: ["전체"])
    start_date: str | None = None
    end_date: str | None = None
    keywords: list[str] = Field(default_factory=list)

    url: str = Field(description="게시글 URL")
