"""정형 표 PDF(교과과정표) 크롤러.

CLAUDE.md §10 결정: 정형 표는 LLM 추출 금지 → pdfplumber 결정론 경로.
1 PDF = 여러 입학년도 표. 입학년도별로 1개 record를 생성해야 RAG가
"2014학년도 입학자 기준" 같은 질문을 임베딩 유사도로 잡을 수 있다.
URL UNIQUE 제약을 우회하기 위해 fragment(#year=…)로 record를 구분.
"""

from __future__ import annotations

import re
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
        # computer.kongju.ac.kr가 옛 TLS만 받음 → SECLEVEL=1로 핸드셰이크 가능.
        self.config.cache_path.parent.mkdir(parents=True, exist_ok=True)
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        req = urllib.request.Request(self.config.pdf_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            self.config.cache_path.write_bytes(resp.read())
        return self.config.cache_path

    def _year_url(self, year_label: str) -> str:
        # fragment는 서버에 전송되지 않으므로 다운로드 동작에 영향 없음.
        slug = year_label.replace(" ", "_")
        return f"{self.config.pdf_url}#year={slug}"

    @staticmethod
    def _expand_years(year_label: str) -> List[int]:
        """라벨에서 적용 연도를 모두 풀어낸다.
        "2011~2014학년도 입학자부터 적용" → [2011, 2012, 2013, 2014]
        "2017 ~ 2020학년도 입학자 적용"   → [2017, 2018, 2019, 2020]
        "2026학년도 입학자 적용"           → [2026]
        """
        rng = re.search(r"(\d{4})\s*~\s*(\d{4})", year_label)
        if rng:
            start, end = int(rng.group(1)), int(rng.group(2))
            if start <= end and end - start <= 20:  # 비정상 범위 방어
                return list(range(start, end + 1))
        return [int(y) for y in re.findall(r"\d{4}", year_label)]

    @staticmethod
    def _lead_sentence(years: List[int]) -> str:
        """임베딩 검색이 '2014학년도' 같은 단일 연도 토큰을 잡도록 첫 줄에 풀어 쓴다."""
        if not years:
            return ""
        enumerated = ", ".join(f"{y}학년도" for y in years)
        return f"이 교육과정은 {enumerated} 입학자에게 적용됩니다."

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        """입학년도별로 1개 record씩 반환. 교과과정표는 항상 풀 재처리이므로 should_skip 미사용."""
        pdf_path = self._download_pdf()
        parsed = parse(pdf_path)
        years = parsed["years"]
        if not years:
            print(f"[{self.SOURCE_CODE}] PDF에서 추출된 연도가 없습니다.")
            return []

        records: List[dict] = []
        for year in years:
            year_label = year.get("year_label") or f"page-{year.get('page_number')}"
            applicable = self._expand_years(year_label)
            lead = self._lead_sentence(applicable)
            body = render_text(year)
            content = f"{lead}\n\n{body}" if lead else body
            title = f"{self.SOURCE_NAME} ({year_label})"
            url = self._year_url(year_label)
            keywords = ["교육과정", "전공", "학점"] + [f"{y}학년도" for y in applicable]
            records.append({
                "title": title,
                "date": "",
                "content": content,
                "url": url,
                "assets": [],
                "pre_refined": True,
                "metadata": {
                    "title": title,
                    "content": content,
                    "target": [self.DEPARTMENT],
                    "start_date": None,
                    "end_date": None,
                    "category": "학사/수업",
                    "keywords": keywords,
                    "url": url,
                },
                "extra": {
                    "curriculum": {"years": [year]},
                    "page_url": self.config.page_url,
                    "applicable_years": applicable,
                },
            })

        labels = [y.get("year_label") for y in years]
        print(f"[{self.SOURCE_CODE}] {len(records)}개 연도 record 생성: {labels}")
        return records
