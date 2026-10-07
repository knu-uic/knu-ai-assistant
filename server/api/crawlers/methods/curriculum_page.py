import hashlib
import json
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path
import urllib.parse
from typing import Callable

from bs4 import BeautifulSoup

from parsers.curriculum import parse, render_text


_PARSE_CACHE_VERSION = 1


@dataclass(frozen=True)
class CurriculumDocumentConfig:
    label: str
    pdf_url: str
    cache_path: Path


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
    documents: tuple[CurriculumDocumentConfig, ...] = ()
    document_selector: str | None = None
    document_url_template: str | None = None
    document_cache_dir: Path | None = None


class CurriculumCrawler:
    KIND = "academic"

    def __init__(self, config: CurriculumConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.BASE_URL = config.base_url

    def _documents(self) -> tuple[CurriculumDocumentConfig, ...]:
        if self.config.document_selector or self.config.document_url_template:
            return self._discover_documents()
        if self.config.documents:
            return self.config.documents
        return (
            CurriculumDocumentConfig(
                label=self.SOURCE_NAME,
                pdf_url=self.config.pdf_url,
                cache_path=self.config.cache_path,
            ),
        )

    def _ssl_context(self):
        ctx = (
            ssl.create_default_context()
            if self.config.verify_ssl
            else ssl._create_unverified_context()
        )
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        return ctx

    def _fetch_document_list_html(self) -> str:
        req = urllib.request.Request(
            self.config.page_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, context=self._ssl_context(), timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _discover_documents(self) -> tuple[CurriculumDocumentConfig, ...]:
        selector = self.config.document_selector
        url_template = self.config.document_url_template
        if not selector or not url_template:
            raise ValueError(
                f"[{self.SOURCE_CODE}] document_selector와 "
                "document_url_template을 함께 설정해야 합니다."
            )

        soup = BeautifulSoup(self._fetch_document_list_html(), "html.parser")
        cache_dir = self.config.document_cache_dir or self.config.cache_path.parent
        documents = []
        seen_ids = set()
        for option in soup.select(selector):
            document_id = str(option.get("value") or "").strip()
            if not document_id or document_id in seen_ids:
                continue
            seen_ids.add(document_id)
            safe_id = "".join(
                char if char.isalnum() or char in {"-", "_"} else "_"
                for char in document_id
            )
            documents.append(CurriculumDocumentConfig(
                label=option.get_text(" ", strip=True) or document_id,
                pdf_url=url_template.format(
                    document_id=urllib.parse.quote(document_id, safe="")
                ),
                cache_path=cache_dir / f"{safe_id}.pdf",
            ))

        if not documents:
            raise RuntimeError(
                f"[{self.SOURCE_CODE}] 교육과정 페이지에서 문서 목록을 찾지 못했습니다."
            )
        return tuple(documents)

    def _download_document(
        self,
        document: CurriculumDocumentConfig | None = None,
    ) -> Path:
        document = document or self._documents()[0]
        document.cache_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            document.pdf_url,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(
            req,
            context=self._ssl_context(),
            timeout=30,
        ) as resp:
            document.cache_path.write_bytes(resp.read())
        return document.cache_path

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        """Return a content hash for an existing cached document."""
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _parse_cache_path(document_path: Path) -> Path:
        return document_path.with_suffix(f"{document_path.suffix}.parsed.json")

    def _load_parse_cache(
        self,
        document_path: Path,
        document_hash: str,
    ) -> dict | None:
        cache_path = self._parse_cache_path(document_path)
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            payload.get("version") != _PARSE_CACHE_VERSION
            or payload.get("sha256") != document_hash
            or not isinstance(payload.get("parsed"), dict)
        ):
            return None
        return payload["parsed"]

    def _store_parse_cache(
        self,
        document_path: Path,
        document_hash: str,
        parsed: dict,
    ) -> None:
        cache_path = self._parse_cache_path(document_path)
        temporary_path = cache_path.with_suffix(f"{cache_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "version": _PARSE_CACHE_VERSION,
                    "sha256": document_hash,
                    "parsed": parsed,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(cache_path)

    def crawling(
        self,
        should_skip: Callable[[str], bool] | None = None,
    ) -> list[dict]:
        documents = self._documents()
        results = []
        for document in documents:
            document_path = self._download_document(document)
            suffix = document_path.suffix.lower()

            if suffix != ".pdf":
                raise RuntimeError(
                    f"[{self.SOURCE_CODE}] 좌표 기반 교육과정 파서는 PDF만 지원합니다: "
                    f"{document_path}. 비PDF 문서는 정확한 전용 구조 파서가 필요합니다."
                )

            document_hash = self._file_sha256(document_path)
            if document_hash is None:
                raise RuntimeError(
                    f"[{self.SOURCE_CODE}] 다운로드한 교육과정 PDF가 없습니다: "
                    f"{document_path}"
                )

            parsed = self._load_parse_cache(document_path, document_hash)
            if parsed is None:
                parsed = parse(document_path)
                if parsed:
                    self._store_parse_cache(document_path, document_hash, parsed)
            if not parsed:
                raise RuntimeError(
                    f"[{self.SOURCE_CODE}] {document.label} curriculum parse 결과 없음"
                )

            years = parsed.get("years")
            if not years:
                raise RuntimeError(
                    f"[{self.SOURCE_CODE}] {document.label} 파싱된 연도 데이터 없음"
                )

            # 모든 입학년도별 페이지를 개별 문서로 분리하여 RAG에 적재
            for item in years:
                year_label = item.get("year_label") or document.label
                title = f"{self.SOURCE_NAME} ({year_label})"
                content = render_text(item).strip()
                applicable_years = item.get("applicable_years") or []

                # DB의 URL 유니크 제약을 피하고 각각 고유 문서로 색인하기 위해 쿼리 파라미터 부여
                doc_url = (
                    f"{document.pdf_url}?year={urllib.parse.quote(year_label)}"
                    f"&page={item['page_number']}"
                )

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
                    "replace_by_source": False,
                    "metadata": {
                        "title": title,
                        "content": content,
                        "summary": f"{self.SOURCE_NAME}의 {year_label} 교육과정표입니다. 전공 교과목, 학점, 이수 구분 등 교육과정 정보를 확인할 수 있습니다.",
                        "target": ["전체"],
                        "start_date": None,
                        "end_date": None,
                        "category": "수강",
                        "url": doc_url,
                    },
                    "extra": {
                        "curriculum": item,
                        "latest_year": year_label,
                        "applicable_years": applicable_years,
                        "document_type": ".pdf",
                        "document_label": document.label,
                        "page_url": self.config.page_url,
                    },
                })

        # 한 소스의 모든 결과가 완성된 뒤, 최초 문서를 저장할 때만 이전
        # 스냅샷을 삭제한다. 결과마다 삭제하면 마지막 문서만 남는다.
        if results:
            results[0]["replace_by_source"] = True
        return results
