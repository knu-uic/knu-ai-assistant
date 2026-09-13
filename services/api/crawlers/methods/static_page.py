from dataclasses import dataclass
from typing import Callable, List, Optional

import requests
from bs4 import BeautifulSoup, Tag


from urllib3.util import create_urllib3_context


class CustomSSLContextAdapter(requests.adapters.HTTPAdapter):
    """구버전 TLS/SSL(SECLEVEL=1)을 허용하도록 urllib3의 SSLContext를 커스텀하는 어댑터."""
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().proxy_manager_for(*args, **kwargs)


@dataclass(frozen=True)
class StaticPageConfig:
    source_code: str
    source_name: str
    department: str | None
    kind: str
    base_url: str
    page_url: str
    wait_selector: str
    title_selector: str
    content_selector: str
    category: str = "기타"
    keywords: tuple[str, ...] = ()


def _clean_text(value: str) -> str:
    return "\n".join(
        line for line in (" ".join(part.split()) for part in value.splitlines())
        if line
    )


def _table_section(table: Tag) -> str | None:
    for node in (table, *table.parents):
        if not isinstance(node, Tag):
            continue
        for sibling in node.find_previous_siblings():
            text = _clean_text(sibling.get_text(" ", strip=True))
            if text and len(text) <= 120:
                return text
    return None


def _unique_headers(values: list[str]) -> list[str]:
    normalized = [value or f"열 {index + 1}" for index, value in enumerate(values)]
    totals = {value: normalized.count(value) for value in set(normalized)}
    seen: dict[str, int] = {}
    result = []
    for value in normalized:
        seen[value] = seen.get(value, 0) + 1
        result.append(
            f"{value} ({seen[value]})" if totals[value] > 1 else value
        )
    return result


def _parse_table(table: Tag, index: int) -> dict:
    table_rows = [
        row for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]
    grid: dict[tuple[int, int], str] = {}
    source_cells = []
    header_row_count = 0
    for row_index, row in enumerate(table_rows):
        if row.find_parent("thead") is not None:
            header_row_count += 1
        column_index = 0
        cells = row.find_all(["th", "td"], recursive=False)
        for cell in cells:
            while (row_index, column_index) in grid:
                column_index += 1
            row_span = max(1, int(cell.get("rowspan") or 1))
            column_span = max(1, int(cell.get("colspan") or 1))
            text = _clean_text(cell.get_text("\n", strip=True))
            source_cells.append({
                "row": row_index,
                "column": column_index,
                "row_span": row_span,
                "column_span": column_span,
                "header": cell.name == "th",
                "text": text,
            })
            for target_row in range(row_index, row_index + row_span):
                for target_column in range(column_index, column_index + column_span):
                    grid[(target_row, target_column)] = text
            column_index += column_span

    column_count = max((column for _, column in grid), default=-1) + 1
    expanded_rows = [
        [grid.get((row, column), "") for column in range(column_count)]
        for row in range(len(table_rows))
    ]
    if header_row_count:
        raw_headers = []
        for column in range(column_count):
            parts = []
            for row in range(header_row_count):
                value = expanded_rows[row][column]
                if value and value not in parts:
                    parts.append(value)
            raw_headers.append(" / ".join(parts))
        data_rows = expanded_rows[header_row_count:]
    else:
        raw_headers = [f"열 {column + 1}" for column in range(column_count)]
        data_rows = expanded_rows
    headers = _unique_headers(raw_headers)
    caption_el = table.find("caption")
    caption = _clean_text(caption_el.get_text(" ", strip=True)) if caption_el else None
    return {
        "index": index,
        "section": _table_section(table),
        "caption": caption,
        "columns": headers,
        "rows": [dict(zip(headers, row)) for row in data_rows],
        "source_cells": source_cells,
    }


def _markdown_table(table: dict) -> str:
    def cell(value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    columns = table["columns"]
    lines = []
    if table.get("caption"):
        lines.append(f"_{table['caption']}_")
    lines.extend([
        "| " + " | ".join(cell(value) for value in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ])
    for row in table["rows"]:
        lines.append("| " + " | ".join(cell(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def _structured_content(content_el: Tag) -> tuple[str, list[dict]]:
    clone = BeautifulSoup(str(content_el), "html.parser")
    tables = []
    for index, table_el in enumerate(clone.find_all("table"), start=1):
        parsed = _parse_table(table_el, index)
        tables.append(parsed)
        table_el.replace_with(f"\n\n{_markdown_table(parsed)}\n\n")
    content = _clean_text(clone.get_text("\n", strip=True))
    return content, tables


class StaticPageCrawler:
    def __init__(self, config: StaticPageConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.KIND = config.kind
        self.BASE_URL = config.base_url

        self.session = requests.Session()
        self.session.mount("https://", CustomSSLContextAdapter())
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            )
        })

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        print(f"\n=== {self.SOURCE_NAME} 수집: {self.config.page_url} ===")

        response = self.session.get(self.config.page_url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        try:
            title_el = soup.select_one(self.config.title_selector)
            title = title_el.get_text(" ", strip=True) if title_el else self.SOURCE_NAME
        except Exception:
            title = self.SOURCE_NAME

        try:
            content_el = soup.select_one(self.config.content_selector)
            content, tables = _structured_content(content_el) if content_el else ("", [])
        except Exception:
            content = ""
            tables = []

        # static page는 대부분 body 중심 문서
        body_content = content
        attachment_names: list[str] = []
        attachment_contents: list[dict] = []

        if not content:
            print(f"[{self.SOURCE_CODE}] 본문 추출 실패")
            return []

        print(f"제목: {title}")
        print(content[:300] + ("..." if len(content) > 300 else ""))

        summary = " ".join(content.split())[:240]

        return [{
            "title": title,
            "date": "",
            "content": content,

            # 신규 구조
            "body_content": body_content,
            "attachment_names": attachment_names,
            "attachment_contents": attachment_contents,

            "url": self.config.page_url,
            "assets": [],
            "replace_by_source": True,
            "extra": {
                "content_format": "markdown_with_structured_tables",
                "table_schema_version": 1,
                "tables": tables,
            } if tables else None,
            # A curated static information page already has a stable source,
            # title, category and body. Avoid a slow, lossy LLM round-trip for
            # metadata that can be produced deterministically.
            "pre_refined": True,
            "metadata": {
                "title": title,
                "content": content,
                "summary": summary,
                "target": ["전체"],
                "start_date": None,
                "end_date": None,
                "category": self.config.category,
                "keywords": list(self.config.keywords),
                "url": self.config.page_url,
            },
        }]
