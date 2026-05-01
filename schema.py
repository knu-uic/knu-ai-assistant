from pydantic import BaseModel, Field
from typing import List, Optional

class MetadataSchema(BaseModel):
    title: str = Field(description='게시판 글 제목')
    content: str = Field(description='게시판 글의 본문 내용을 한 문단으로 요약한 텍스트')
    target: List[str] = Field(description="지원 가능한 대상 학과 (예: ['컴퓨터공학과', '소프트웨어학과'], 무관할경우 ['전체'])")
    deadline: Optional[str] = Field(description="접수기간 (예: yyyy-mm-dd ~ yyyy-mm-dd)")
    category: str = Field(description="글의 카테고리 (예: 수강신청, 장학, 대회, 어학연수, 학점교류, 공모전, 교내행사, 학사 등등)")
    url: str = Field(description="게시글의 url")