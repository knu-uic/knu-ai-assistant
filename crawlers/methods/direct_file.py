import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from attachments import hwp_bytes_to_text


@dataclass(frozen=True)
class DirectFileConfig:
    source_code: str
    source_name: str
    department: str
    base_url: str
    file_url: str
    page_url: str
    cache_path: Path
    category: str
    keywords: list[str]
    filename: str
    mime_type: str = "application/octet-stream"
    verify_ssl: bool = True


class DirectFileCrawler:
    KIND = "academic"

    def __init__(self, config: DirectFileConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

    def _download_file(self) -> bytes:
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = (
            ssl.create_default_context()
            if self.config.verify_ssl
            else ssl._create_unverified_context()
        )
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        req = urllib.request.Request(self.config.file_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = resp.read()
        self.config.cache_path.write_bytes(data)
        return data

    def _extract_text(self, data: bytes) -> str:
        if self.config.filename.lower().endswith(".hwp"):
            text = hwp_bytes_to_text(data, self.config.filename)
            if text:
                return text
        return f"({self.config.filename} 파일 텍스트를 추출하지 못했습니다. 원본 다운로드: {self.config.file_url})"

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        if should_skip and should_skip(self.config.file_url):
            print(f"[{self.SOURCE_CODE}] DB에 이미 적재됨 - 스킵")
            return []

        data = self._download_file()
        content = self._extract_text(data)
        title = self.SOURCE_NAME
        summary = f"{self.SOURCE_NAME}입니다. 교과목, 학년별 이수 정보, 전공 교과목 정보를 확인할 수 있습니다."

        return [{
            "title": title,
            "date": "",
            "content": content,
            "url": self.config.file_url,
            "assets": [{
                "kind": "attachment_hwp",
                "filename": self.config.filename,
                "source_url": self.config.file_url,
                "storage_path": str(self.config.cache_path),
                "mime_type": self.config.mime_type,
                "extracted_text": content,
                "order_idx": 0,
            }],
            "pre_refined": True,
            "metadata": {
                "title": title,
                "content": content,
                "summary": summary,
                "target": ["전체"],
                "start_date": None,
                "end_date": None,
                "category": self.config.category,
                "keywords": self.config.keywords,
                "url": self.config.file_url,
            },
            "extra": {
                "page_url": self.config.page_url,
                "file_path": str(self.config.cache_path),
            },
        }]
