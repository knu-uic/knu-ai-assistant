import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from curriculum_parser import parse, render_text


@dataclass(frozen=True)
class CurriculumConfig:
    source_code: str
    source_name: str
    department: str
    base_url: str
    pdf_url: str
    page_url: str
    cache_path: Path


class CurriculumCrawler:
    KIND = "academic"

    def __init__(self, config: CurriculumConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

    def _download_pdf(self) -> Path:
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        req = urllib.request.Request(self.config.pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            self.config.cache_path.write_bytes(resp.read())
        return self.config.cache_path

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        pdf_path = self._download_pdf()
        parsed = parse(pdf_path)
        years = parsed["years"]
        if not years:
            print(f"[{self.SOURCE_CODE}] PDF에서 추출된 연도가 없습니다.")
            return []

        latest = years[-1]
        content = render_text(latest)
        title = f"{self.SOURCE_NAME} ({latest.get('year_label') or '최신'})"
        print(f"[{self.SOURCE_CODE}] {len(years)}개 연도 파싱 완료. 최신: {latest.get('year_label')}")

        return [{
            "title": title,
            "date": "",
            "content": content,
            "url": self.config.pdf_url,
            "assets": [],
            "pre_refined": True,
            "metadata": {
                "title": title,
                "content": content,
                "summary": f"{self.SOURCE_NAME}의 {latest.get('year_label') or '최신'} 교육과정표입니다. 전공 교과목, 학점, 이수 구분 등 교육과정 정보를 확인할 수 있습니다.",
                "target": [self.DEPARTMENT],
                "start_date": None,
                "end_date": None,
                "category": "학사/수업",
                "keywords": ["교육과정", "전공", "학점"],
                "url": self.config.pdf_url,
            },
            "extra": {
                "curriculum": parsed,
                "page_url": self.config.page_url,
            },
        }]
