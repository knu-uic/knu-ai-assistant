from pydantic import BaseModel, Field
from typing import List, Optional

class MetadataSchema(BaseModel):
    title: str = Field(description='게시판 글 제목')
    content: str = Field(description='게시판 글의 본문 내용을 한 문단으로 요약한 텍스트')
    target: List[str] = Field(description="본문 내용을 토대로 어떤 학과의 학생 또는 어떤것에 관심이 있는 학생이 참여하면 좋을지 기재")
    deadline: Optional[str] = Field(description="접수기간 (예: yyyy-mm-dd ~ yyyy-mm-dd)")
    category: str = Field(description="본문을 토대로 파악한 글의 카테고리")
    url: str = Field(description="게시글의 url")