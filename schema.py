from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class MetadataSchema(BaseModel):
    title: str = Field(description='게시판 글 제목')
    content: str = Field(description='게시판 글의 본문 내용을 한 문단으로 요약한 텍스트')
    
    # [수정 1] 타겟은 무조건 '소속(자격)'만 엄격하게! (관심사 섞기 금지)
    target: List[str] = Field(
        description=(
            "참여 가능한 대상의 '학과' 또는 '학년'만 추출한다. "
            "나이/지역/거주/직업/관심사 등 인구통계 조건은 절대 포함하지 않는다. "
            "학과/학년 제한이 본문에 명시되지 않았다면 무조건 ['전체']. "
            "예: ['컴퓨터공학과', '3학년'], ['전체']"
        )
    )
    
    start_date: Optional[str] = Field(description="접수 시작일 (yyyy-mm-dd 형식). 본문에 없으면 null")
    end_date: Optional[str] = Field(description="접수 마감일 (yyyy-mm-dd 형식). 본문에 없으면 null")
    
    # [수정 2] 대학교의 모든 범주를 커버하는 '고정형 대분류' (DB의 게시판 탭 역할)
    category: Literal["장학/등록", "학사/수업", "진로/취업", "행사/공모전", "일반/기타"] = Field(description="글의 대분류 카테고리")
    
    # [수정 3] 유연성을 100% 보장하는 '개방형 키워드' 추가 (유사도 검색 및 해시태그 역할)
    keywords: List[str] = Field(description="본문의 핵심 주제나 관심사를 나타내는 단어 3개 (예: ['해커톤', '인공지능', 'AWS'])")
    
    url: str = Field(description="게시글의 url")