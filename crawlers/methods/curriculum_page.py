import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable

from parsers.curriculum import parse, render_text
from extractors.attachments import extract_attachment_text


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

        parsed = None
        latest = {}

        # PDF curriculum은 구조 parser 사용.
        if suffix == ".pdf":
            parsed = parse(document_path)

            if not parsed:
                print(f"[{self.SOURCE_CODE}] curriculum parse 결과 없음")
                return []

            years = parsed["years"]
            latest = years[-1] if years else {}

            content = render_text(latest).strip()

        # HWP/HWPX/XLSX 등은 generic extractor fallback.
        else:
            content = extract_attachment_text(document_path).strip()

        if not content:
            print(f"[{self.SOURCE_CODE}] curriculum render 결과 비어있음")
            return []

        # curriculum은 static-style 본문 문서로 취급.
        # 실제 교과과정 내용은 body/content에 직접 유지한다.
        body_content = content

        attachment_names: list[str] = []
        attachment_contents: list[dict] = []

        year_label = latest.get("year_label") or "최신"
        title = f"{self.SOURCE_NAME} ({year_label})"
        if parsed:
            print(f"[{self.SOURCE_CODE}] {len(years)}개 연도 파싱 완료. 최신: {year_label}")
        else:
            print(f"[{self.SOURCE_CODE}] generic curriculum extractor 사용: {document_path.name}")

        return [{
            "title": title,
            "date": "",
            # curriculum 전체 내용을 static-style content로 유지
            "content": body_content,

            # 신규 구조
            "body_content": body_content,
            "attachment_names": attachment_names,
            "attachment_contents": attachment_contents,

            "url": self.config.pdf_url,
            "assets": [],
            "pre_refined": True,
            "replace_by_source": True,
            "metadata": {
                "title": title,
                "content": body_content,
                "summary": f"{self.SOURCE_NAME}의 {year_label} 교육과정표입니다. 전공 교과목, 학점, 이수 구분 등 교육과정 정보를 확인할 수 있습니다.",
                "target": ["전체"],
                "start_date": None,
                "end_date": None,
                "category": "수강",
                "keywords": ["교육과정", "전공", "학점"],
                "url": self.config.pdf_url,
            },
            "extra": {
                "curriculum": parsed,
                "latest_year": year_label,
                "document_type": document_path.suffix.lower(),
                "page_url": self.config.page_url,
            },
        }]
