"""DB row tuple → API schema 매핑. 날짜는 ISO 문자열, target/keywords는 list[str]로 정규화."""
import math

from interfaces.http.schemas.notices import NoticeItem
from interfaces.http.schemas.search import SearchResult


def _iso(x):
    if x is None:
        return None
    return x.isoformat() if hasattr(x, "isoformat") else str(x)


def _score(x) -> float:
    # search_chunks가 임베딩 없는 청크에서 NaN 점수를 낼 수 있음(1 - (NULL <=> vec)).
    # NaN은 JSON에서 null로 직렬화돼 dart 계약(비-null double)을 깨므로 0.0으로 강등.
    return x if isinstance(x, (int, float)) and math.isfinite(x) else 0.0


def _strlist(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x]
    if isinstance(x, str):
        return [s.strip() for s in x.split(",") if s.strip()]
    return []


def notice_from_list_row(row) -> NoticeItem:
    (url, title, content, posted_at, start_date, end_date, category,
     target, keywords, _code, source_name, _kind, _dept, *rest) = row
    summary = rest[0] if rest else None
    return NoticeItem(
        url=url, title=title, content=content, summary=summary,
        posted_at=_iso(posted_at), start_date=_iso(start_date), end_date=_iso(end_date),
        category=category, target=_strlist(target), keywords=_strlist(keywords),
        source_name=source_name,
    )


def result_from_search_row(row) -> SearchResult:
    (url, title, snippet, score, posted_at, start_date, end_date, category,
     _target, _keywords, _code, _name, _kind, _dept, *rest) = row
    summary = rest[0] if rest else None
    return SearchResult(
        url=url, title=title, snippet=snippet, score=_score(score),
        posted_at=_iso(posted_at), start_date=_iso(start_date), end_date=_iso(end_date),
        category=category, summary=summary,
    )
