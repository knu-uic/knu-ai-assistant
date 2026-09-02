import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
import urllib.parse
from urllib.parse import urlparse
from typing import Callable

from parsers.curriculum import parse, render_text


@dataclass(frozen=True)
class CurriculumConfig:
    source_code: str
    source_name: str
    department: str
    base_url: str
    pdf_url: str
    page_url: str
    cache_path: Path
    verify_ssl: bool = True


class CurriculumCrawler:
    KIND = "academic"

    def __init__(self, config: CurriculumConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

    def _download_document(self) -> Path:
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = (
            ssl.create_default_context()
            if self.config.verify_ssl
            else ssl._create_unverified_context()
        )
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        req = urllib.request.Request(
            self.config.pdf_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            self.config.cache_path.write_bytes(resp.read())
        return self.config.cache_path

    def crawling(
        self,
        should_skip: Callable[[str], bool] | None = None,
    ) -> list[dict]:
        document_path = self._download_document()

        suffix = document_path.suffix.lower()
        results = []

        if suffix != ".pdf":
            raise RuntimeError(
                f"[{self.SOURCE_CODE}] 좌표 기반 교육과정 파서는 PDF만 지원합니다: "
                f"{document_path}. 비PDF 문서는 정확한 전용 구조 파서가 필요합니다."
            )
        target_pdf_path = document_path

        parsed = parse(target_pdf_path)

        if not parsed:
            raise RuntimeError(f"[{self.SOURCE_CODE}] curriculum parse 결과 없음")

        years = parsed.get("years")
        if not years:
            raise RuntimeError(f"[{self.SOURCE_CODE}] 파싱된 연도 데이터 없음")

        # 모든 입학년도별 페이지를 개별 문서로 분리하여 RAG에 적재
        for item in years:
            year_label = item.get("year_label") or "최신"
            title = f"{self.SOURCE_NAME} ({year_label})"
            content = render_text(item).strip()
            applicable_years = item.get("applicable_years") or []

            # DB의 URL 유니크 제약을 피하고 각각 고유 문서로 색인하기 위해 쿼리 파라미터 부여
            doc_url = f"{self.config.pdf_url}?year={urllib.parse.quote(year_label)}&page={item['page_number']}"

            keywords = ["교육과정", "전공", "학점", year_label] + [
                f"{year}학년도" for year in applicable_years
            ]

            results.append({
                    "title": title,
                    "date": "",
                    "content": content,
                    "body_content": content,
                    "attachment_names": [],
                    "attachment_contents": [],
                    "url": doc_url,
                    "assets": [],
                    "pre_refined": True,
                    "replace_by_source": True,
                    "metadata": {
                        "title": title,
                        "content": content,
                        "summary": f"{self.SOURCE_NAME}의 {year_label} 교육과정표입니다. 전공 교과목, 학점, 이수 구분 등 교육과정 정보를 확인할 수 있습니다.",
                        "target": ["전체"],
                        "start_date": None,
                        "end_date": None,
                        "category": "수강",
                        "keywords": keywords,
                        "url": doc_url,
                    },
                    "extra": {
                        "curriculum": item,
                        "latest_year": year_label,
                        "applicable_years": applicable_years,
                        "document_type": ".pdf",
                        "page_url": self.config.page_url,
                    },
            })
        return results
