"""data/curriculums/**/<key>*.pdf 를 DB에 적재한다.

정책: 커리큘럼은 사람이 손으로 정제한 PDF를 data/curriculums/에 두고 이 스크립트로
적재. 1 PDF = 여러 입학년도 페이지 → 입학년도별 1 document로 분리.

파일 배치:
- DATA_DIR(=data/curriculums) 하위 임의 깊이로 폴더 구조화 가능 (rglob 재귀 매칭).
  예: data/curriculums/공과대학/컴퓨터공학과/cse_curriculum_2024.pdf
- 파일명은 registry key 로 시작하면 끝 자유롭게 (archive 패턴 지원):
  cse_curriculum_2024.pdf, cse_curriculum_2025.pdf 등 모두 cse_curriculum key 매칭.

URL:
- local://curriculum/<key>#year=<year_slug> 형태의 의사 URL.
  파일명이 아니라 key 기반이라 archive 파일 여러 개여도 url 정체성이 학과 단위로 고정.
- insert_document 의 ON CONFLICT (url) UPDATE 가 곧 UPSERT 역할 — 같은 url 재실행 시
  content/title/keywords/extra 갱신되고 document_id 유지, chunk 는 insert_chunks 가
  document_id 기준 delete+insert 하므로 결과적으로 풀 재처리와 동일.
- 같은 key 의 PDF 여러 개에서 같은 year_label 이 두 번 등장하면 stderr 경고 출력
  (의도된 archive 덮어쓰기일 수도, 실수일 수도 — 관리자가 판단).

학과 추가 절차:
1. data/curriculums/<원하는 폴더>/<key>*.pdf 드롭.
2. 아래 CURRICULUM_REGISTRY 에 {key: {name, department, page_url}} 한 줄 추가.
3. docker compose exec app python scripts/ingest_curriculum_local.py 실행.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

# 스크립트를 컨테이너 밖(루트 cwd)에서 실행할 때도 패키지 import가 동작하도록 경로 보정.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from db import insert_assets, insert_chunks, insert_document, upsert_source
from embed import embed_chunks
from parsers.curriculum_parser import parse, render_text


DATA_DIR = _PROJECT_ROOT / "data" / "curriculums"

# 학과 메타데이터. key 는 PDF 파일명 prefix + URL 식별자 역할.
# 학과 메타데이터. key 는 PDF 파일명 prefix + URL 식별자 역할.
CURRICULUM_REGISTRY: dict[str, dict] = {
    "cse_curriculum": {
        "name": "컴퓨터공학과 교육과정",
        "department": "컴퓨터공학과",
        "page_url": "https://computer.kongju.ac.kr/ZD1140/11579/subview.do",
    },
    # 👇 방금 추가하신 전기전자제어공학부 전공들
    "ee_electrical": {
        "name": "전기공학전공 교육과정",
        "department": "전기전자제어공학부 전기공학전공",
        "page_url": "https://elecnt.kongju.ac.kr/ZD1510/4062/subview.do", # 실제 홈페이지 주소로 변경 권장
    },
    "ee_electronic": {  # 파일명에 적으신 스펠링 그대로 등록!
        "name": "전자공학전공 교육과정",
        "department": "전기전자제어공학부 전자공학전공",
        "page_url": "https://electron.kongju.ac.kr/ZD1520/4794/subview.do",
    },
    "ee_control": {
        "name": "제어계측공학전공 교육과정",
        "department": "전기전자제어공학부 제어계측공학전공",
        "page_url": "https://control.kongju.ac.kr/ZD1530/4084/subview.do",
    },
    "ee_semiconductor": {
        "name": "반도체정보공학전공 교육과정",
        "department": "전기전자제어공학부 반도체정보공학전공",
        "page_url": "https://image.kongju.ac.kr/ZD1540/6126/subview.do",
    },
}



def _expand_years(year_label: str) -> list[int]:
    """라벨에서 적용 연도를 모두 풀어낸다.

    - "2011~2014학년도 입학자부터 적용" → [2011, ..., 2014] (range)
    - "2024학년도부터 적용"             → [2024, ..., 현재+1] (단일 연도 자동 확장)
    - "2014학년도 입학자 적용"          → [2014, ..., 현재+1] ("부터" 없어도 동일 확장)

    설계 의도: PDF 표에 "X학년도"만 적혀 있어도 의미는 "X학년도부터 새 커리큘럼이
    나올 때까지 계속 적용". 따라서 단일 연도는 항상 현재 학년도+1까지 확장해 RAG
    검색 매칭률을 끌어올린다. 신규 PDF가 도착하면 archive 순차 덮어쓰기 정책으로
    자연히 갱신되므로 over-coverage 무해.
    """
    rng = re.search(r"(\d{4})\s*~\s*(\d{4})", year_label)
    if rng:
        start, end = int(rng.group(1)), int(rng.group(2))
        if start <= end and end - start <= 20:
            return list(range(start, end + 1))

    years = [int(y) for y in re.findall(r"\d{4}", year_label)]

    if len(years) == 1:
        start_year = years[0]
        current_year = datetime.date.today().year
        # max() 가드: 미래 시작년(예: 2030학년도 표시)을 받아도 빈 리스트 대신 [start] 유지.
        target_end = max(start_year, current_year + 1)
        return list(range(start_year, target_end + 1))

    return years


def _lead_sentence(years: list[int]) -> str:
    """임베딩 검색이 '2014학년도' 같은 단일 연도 토큰을 잡도록 첫 줄에 풀어 쓴다."""
    if not years:
        return ""
    enumerated = ", ".join(f"{y}학년도" for y in years)
    return f"이 교육과정은 {enumerated} 입학자에게 적용됩니다."


def _pseudo_url(key: str, year_label: str) -> str:
    """url UNIQUE 제약을 우회하기 위해 fragment(#year=…)로 record 구분.
    파일명 대신 registry key 사용 — 같은 학과의 archive 파일이 여러 개여도
    url 정체성이 학과(key) 단위로 고정되어 UPSERT 가 자연스럽게 동작.
    """
    slug = year_label.replace(" ", "_")
    return f"local://curriculum/{key}#year={slug}"


def ingest(pdf_path: Path, meta: dict, key: str, seen_urls: set[str]) -> int:
    """1 PDF → 입학년도별 document 적재. 같은 key 의 다른 PDF 에서 이미 등록한 url 을
    또 만나면 stderr 경고 (archive overwrite 감지). 등록 개수 반환.
    """
    parsed = parse(pdf_path)
    years = parsed["years"]
    if not years:
        print(f"[{pdf_path.name}] PDF에서 추출된 연도가 없습니다.")
        return 0

    source_id = upsert_source(
        code=key,
        name=meta["name"],
        kind="academic",
        department=meta["department"],
        base_url="local://curriculum",
    )

    count = 0
    for year in years:
        year_label = year.get("year_label") or f"page-{year.get('page_number')}"
        url = _pseudo_url(key, year_label)

        if url in seen_urls:
            print(
                f"[warn] 덮어쓰기 감지: {url} "
                f"({pdf_path.name}이 이전 PDF의 동일 연도 record를 덮어씁니다)",
                file=sys.stderr,
            )
        seen_urls.add(url)

        applicable = _expand_years(year_label)
        lead = _lead_sentence(applicable)
        body = render_text(year)
        content = f"{lead}\n\n{body}" if lead else body
        title = f"{meta['name']} ({year_label})"
        keywords = ["교육과정", "전공", "학점"] + [f"{y}학년도" for y in applicable]
        extra = {
            "curriculum": {"years": [year]},
            "page_url": meta["page_url"],
            "applicable_years": applicable,
        }

        document_id = insert_document(
            source_id=source_id,
            url=url,
            title=title,
            content=content,
            start_date=None,
            end_date=None,
            category="학사/수업",
            target=[meta["department"]],
            keywords=keywords,
            extra=extra,
            posted_at=None,
        )
        insert_assets("학사/수업", document_id, [])
        chunks = embed_chunks(f"{title}\n\n{content}")
        insert_chunks("학사/수업", document_id, chunks)
        count += 1

    return count


def main() -> None:
    if not DATA_DIR.exists():
        print(f"[error] {DATA_DIR} 디렉토리 없음. 먼저 PDF를 드롭하세요.")
        return

    total = 0
    for key, meta in CURRICULUM_REGISTRY.items():
        # rglob: 하위 폴더 임의 깊이까지 재귀 매칭. 운영자가 단과대학/학부/학과 단위로
        # 자유롭게 디렉토리 구조화 가능. 파일명 알파벳 정렬로 처리 순서 결정적.
        pdfs = sorted(DATA_DIR.rglob(f"{key}*.pdf"))
        if not pdfs:
            print(f"[skip] {key}: 매칭 파일 없음")
            continue

        seen_urls: set[str] = set()
        key_total = 0
        for pdf_path in pdfs:
            n = ingest(pdf_path, meta, key, seen_urls)
            print(f"[ok] {pdf_path.relative_to(_PROJECT_ROOT)}: {n}개 record")
            key_total += n
        print(f"[done] {key}: 총 {key_total}개 record ({len(pdfs)}개 PDF)")
        total += key_total

    print(f"=== 완료. 총 {total}개 record 적재 ===")


if __name__ == "__main__":
    main()
