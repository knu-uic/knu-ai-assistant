import time
from datetime import date, datetime
from typing import Any, List, Tuple, cast
import httpx
from langchain_core.messages import SystemMessage, HumanMessage
from model import get_llm
from schema import MetadataSchema
from dotenv import load_dotenv


# Gemini API가 가끔 응답 전 connection을 drop. 재시도로 흡수.
_RETRYABLE_EXC = (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError)
_MAX_ATTEMPTS = 4
_BACKOFF_BASE = 2.0  # 2s, 4s, 8s
# Gemini Tier 1 RPM 1000 — 동시성 10이면 RPM 600 정도라 안전 마진.
_BATCH_CONCURRENCY = 10
# 메타데이터 추출에는 첨부 원문 전체가 필요 없다. 긴 XLSX/PDF가 붙은
# 공지는 LLM 입력만 줄이고, 저장/임베딩에는 원문을 보존한다.
_REFINE_FULL_CONTENT_LIMIT = 3200
_REFINE_ASSET_NAME_LIMIT = 12


SYSTEM_PROMPT = """
너는 공주대학교 공지사항을 구조화된 메타데이터로 변환하는 분석가다.

원칙:
- 본문에 명시된 사실만 사용한다. 추측·창작·일반 상식 추가 금지.
- 입력에 없는 정보는 null 또는 기본값으로 처리한다.
- 모든 출력은 한국어로 작성한다.
"""


def _user_prompt(item: dict) -> str:
    return f"""
다음 공주대 공지를 분석해서 스키마에 맞게 추출해라.

# 입력
- 제목: {item['title']}
- URL: {item['url']}
- 등록일: {item.get('date') or '미상'}
- 본문:
{item['content']}

# 필드별 규칙
## target
- 본문에서 **학과명** 또는 **학년**만 추출한다. 그 외에는 절대 넣지 않는다.
- 학과/학년 제한이 본문에 명시되지 않았다면 **무조건 `["전체"]`**.

### 절대 target에 넣지 말 것 (이 조건들만 있으면 ["전체"]로 처리):
- 나이 (예: "19세~39세 청년", "만 35세 이하")
- 지역/거주 (예: "대구 거주자", "수도권 외 지역", "OO시 주민등록자")
- 직업/직장 상태 (예: "재직자", "구직자", "프리랜서")
- 관심사/취향 (예: "AI에 관심있는 사람", "창업에 관심있는 학생")
- 국적/성별/소득 등 그 밖의 인구통계 조건

### target에 넣어도 되는 것:
- 학과명 (예: "컴퓨터공학과", "전자공학과", "공과대학")
- 학년 (예: "1학년", "3학년", "신입생", "졸업예정자")
- 학적 상태 (예: "재학생", "휴학생") — 학교 단위로 명시된 경우만

### 예시
- 본문: "컴퓨터공학과 3학년 대상" → ["컴퓨터공학과", "3학년"]
- 본문: "19세~39세 대구 외 거주 청년" → ["전체"]   (학과/학년 제한 없음)
- 본문: "재직자 우대, 전 학년 누구나" → ["전체"]   (재직자는 제외, "전 학년"은 제한 없음)
- 본문: "공과대학 재학생 한정" → ["공과대학", "재학생"]

## category
- 다음 5가지 대분류 중 가장 적합한 **단 1개**만 무조건 선택한다.
  1. 장학/등록 (국가장학금, 등록금 납부 등)
  2. 학사/수업 (수강신청, 휴학, 졸업, 성적 등)
  3. 진로/취업 (채용, 인턴, 자격증, 취업특강 등)
  4. 행사/공모전 (대회, 해커톤, 동아리, 축제 등)
  5. 일반/기타 (분실물, 시설안내, 예비군 등 위 4개에 속하지 않는 모든 것)

## keywords
- 본문의 핵심 주제, 혜택, 다루는 기술 등 사용자가 관심 가질만한 해시태그 단어를 1~3개 추출한다.
- 예시: ["멘토링"], ["해외연수", "어학"], ["파이썬", "특강"]

## summary
- 공지의 핵심 내용을 2~3문장으로 요약한다.
- 대상, 기간, 장소, 신청/참여 방법, 혜택, 문의처가 명시되어 있으면 포함한다.
- 본문에 없는 사실은 절대 추가하지 않는다.
- 날짜는 본문에 적힌 표현을 기준으로 하되, 연도 없는 날짜는 게시글 등록연도 기준으로 해석한다.

## start_date / end_date
- 접수기간을 시작일(start_date)과 마감일(end_date)로 분리해서 각각 yyyy-mm-dd 형식으로 추출한다.
- "2026-04-15 ~ 2026-05-04" → start_date="2026-04-15", end_date="2026-05-04"
- 마감일만 있는 경우(예: "~ 2026-05-04", "5월 4일까지") → start_date=null, end_date="2026-05-04"
- 시작일만 있는 경우 → start_date만 채우고 end_date=null
- 본문에 날짜가 전혀 없으면 둘 다 null.
	"""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n... [LLM 입력 축소: {len(text)}자 중 {limit}자만 포함]"


def _content_before_first_attachment(content: str) -> str:
    markers = ["\n[첨부:"]
    positions = [content.find(marker) for marker in markers if content.find(marker) != -1]
    if not positions:
        return content
    return content[:min(positions)]


def _asset_name_lines(assets: list[dict]) -> list[str]:
    lines = []
    for asset in assets[:_REFINE_ASSET_NAME_LIMIT]:
        extracted = asset.get("extracted_text") or ""
        filename = asset.get("filename") or "(본문 이미지)"
        lines.append(
            f"- {asset.get('kind')}: {filename} (추출 {len(extracted)}자)"
        )
    return lines


def _parse_posted_year(raw: str | None) -> int | None:
    """게시글 등록일에서 연도만 뽑는다. 실패하면 None."""
    if not raw:
        return None
    s = raw.strip()
    if not s or "찾을 수 없음" in s:
        return None
    s = s.split()[0].replace(".", "-").replace("/", "-").rstrip("-")
    try:
        return datetime.strptime(s, "%Y-%m-%d").year
    except ValueError:
        pass
    try:
        return int(s.split("-")[0])
    except (ValueError, TypeError, IndexError):
        return None


def _adjust_relative_date_year(value: str | None, posted_year: int | None, evidence: str) -> str | None:
    """LLM이 연도 없는 날짜에 임의 연도를 붙인 경우 게시글 등록연도로 보정한다.

    원문에 LLM이 고른 연도가 직접 등장하면 명시 날짜일 가능성이 있으므로 건드리지 않는다.
    """
    if not value or posted_year is None:
        return value
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    if parsed.year == posted_year:
        return value
    if str(parsed.year) in evidence:
        return value
    try:
        return parsed.replace(year=posted_year).isoformat()
    except ValueError:
        return value


def _adjust_result_dates(result: MetadataSchema, item: dict) -> None:
    posted_year = _parse_posted_year(item.get("date"))
    evidence = "\n".join([
        item.get("title") or "",
        item.get("content") or "",
    ])
    result.start_date = _adjust_relative_date_year(result.start_date, posted_year, evidence)
    result.end_date = _adjust_relative_date_year(result.end_date, posted_year, evidence)


def _llm_item(item: dict) -> dict:
    """LLM 메타데이터 추출용 입력 축소본. 원본 item은 저장 단계에서 보존된다.

    짧은 공지는 전체 텍스트를 그대로 보낸다. 긴 공지는 본문 앞부분과
    첨부파일 목록만 전달한다.
    """
    content = item.get("content") or ""
    if len(content) <= _REFINE_FULL_CONTENT_LIMIT:
        return item

    assets = item.get("assets") or []
    body_text = _content_before_first_attachment(content)
    asset_names = "\n".join(_asset_name_lines(assets))
    body_budget = _REFINE_FULL_CONTENT_LIMIT - len(asset_names) - 120
    compact_parts = [
        "[본문 앞부분]",
        _clip(body_text, max(800, body_budget)),
    ]
    if asset_names:
        compact_parts.extend(["", "[첨부파일 목록]", asset_names])
    compact_parts.append(
        f"\n[원문 길이: {len(content)}자, 저장/임베딩에는 원문 전체 사용]"
    )

    compact = dict(item)
    compact["content"] = "\n".join(compact_parts)
    return compact


def refine(crawled_data: List[dict]) -> List[Tuple[MetadataSchema, List[dict], dict | None]]:
    """크롤링 결과를 LLM으로 구조화 + 원본 assets + extra(JSONB)를 동행시켜 반환.

    반환: [(MetadataSchema, assets, extra), ...]  (입력 순서 유지)
      - MetadataSchema: LLM이 추출한 정규화 메타데이터 (pre_refined면 크롤러가 직접 채움)
      - assets: crawler가 모은 asset 메타 리스트
      - extra: document.extra(JSONB)로 저장할 비정형 데이터 dict (없으면 None)

    크롤러가 `pre_refined=True`를 세팅하면 LLM 호출 없이 `metadata` dict를 그대로 사용.
    정형 데이터(교과과정표 등)는 LLM 환각 피하려고 이 경로 사용.

    LLM 호출이 필요한 항목은 model.batch()로 병렬 처리 후, 실패한 항목만 단건 재시도.
    """
    load_dotenv()
    system_msg = SystemMessage(content=SYSTEM_PROMPT)

    # 인덱스를 보존해서 batch 결과를 원래 순서에 다시 꽂는다.
    needs_llm: List[Tuple[int, dict]] = []
    results: List[MetadataSchema | None] = [None] * len(crawled_data)

    for idx, item in enumerate(crawled_data):
        if item.get("pre_refined"):
            results[idx] = MetadataSchema(**item["metadata"])
        else:
            needs_llm.append((idx, _llm_item(item)))

    if needs_llm:
        model = get_llm().with_structured_output(MetadataSchema)
        prompts = [
            [system_msg, HumanMessage(content=_user_prompt(item))]
            for _, item in needs_llm
        ]
        # return_exceptions=True: 한 항목 실패해도 batch 전체가 죽지 않고 자리에 예외 객체가 들어옴.
        batch_out = model.batch(
            cast(Any, prompts),
            config={"max_concurrency": _BATCH_CONCURRENCY},
            return_exceptions=True,
        )
        for (idx, llm_item), out in zip(needs_llm, batch_out):
            original_item = crawled_data[idx]
            if isinstance(out, Exception):
                # batch에서 죽은 항목만 단건 retry로 흡수 (네트워크 흔들림 대부분 여기서 회복)
                print(f"  ↻ batch 실패 항목 단건 재시도 [{original_item.get('url')}] — {type(out).__name__}")
                out = _invoke_with_retry(model, system_msg, llm_item)
                if out is None:
                    continue  # 끝까지 실패 → 이 항목만 드롭
            result = cast(MetadataSchema, out)
            # LLM이 content를 요약/축약하면 RAG 청크화 시 정보 손실 → 항상 원본 덮어쓰기.
            result.content = original_item["content"]
            result.title = original_item["title"]
            result.url = original_item["url"]
            result.summary = (result.summary or "").strip()
            results[idx] = result

    refined: List[Tuple[MetadataSchema, List[dict], dict | None]] = []
    for idx, item in enumerate(crawled_data):
        result = results[idx]
        if result is None:
            continue  # LLM 끝까지 실패한 항목은 스킵
        _adjust_result_dates(result, item)
        refined.append((result, item.get("assets", []), item.get("extra")))
    return refined


def _invoke_with_retry(model, system_msg: SystemMessage, item: dict) -> MetadataSchema | None:
    """Gemini API 호출에 지수 백오프 재시도. 모든 시도 실패 시 None 반환."""
    user_msg = HumanMessage(content=_user_prompt(item))
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return cast(MetadataSchema, model.invoke([system_msg, user_msg]))
        except _RETRYABLE_EXC as e:
            if attempt == _MAX_ATTEMPTS:
                print(f"  ⚠️ refine 실패 [{item.get('url')}] — {type(e).__name__}: {e}")
                return None
            wait = _BACKOFF_BASE ** attempt
            print(f"  ↻ refine 재시도 {attempt}/{_MAX_ATTEMPTS} ({type(e).__name__}) — {wait:.0f}s 대기")
            time.sleep(wait)
    return None
