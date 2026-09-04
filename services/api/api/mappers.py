"""DB row tuple → API schema 매핑. 날짜는 ISO 문자열, target/keywords는 list[str]로 정규화."""
import math
from datetime import date, datetime

from interfaces.http.schemas.notices import NoticeItem
from interfaces.http.schemas.search import SearchResult
from api.figures import related_figures


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


def _deadline(end_date) -> tuple[str | None, str | None]:
    if end_date is None:
        return None, None
    if isinstance(end_date, datetime):
        value = end_date.date()
    elif isinstance(end_date, date):
        value = end_date
    else:
        try:
            value = date.fromisoformat(str(end_date))
        except ValueError:
            return f"~ {end_date}", "accent"
    remaining = (value - date.today()).days
    if remaining < 0:
        return "마감", "neutral"
    if remaining == 0:
        return "오늘 마감", "danger"
    if remaining <= 7:
        return f"D-{remaining}", "danger"
    if remaining <= 30:
        return f"D-{remaining}", "warning"
    return f"~ {value.isoformat()}", "accent"


def notice_from_list_row(row) -> NoticeItem:
    (url, title, content, posted_at, start_date, end_date, category,
     target, keywords, _code, source_name, _kind, department, *rest) = row
    summary = rest[0] if rest else None
    deadline_label, deadline_tone = _deadline(end_date)
    return NoticeItem(
        url=url, title=title, content=content, summary=summary,
        posted_at=_iso(posted_at), start_date=_iso(start_date), end_date=_iso(end_date),
        category=category, target=_strlist(target), keywords=_strlist(keywords),
        source_name=source_name, department=department,
        deadline_label=deadline_label, deadline_tone=deadline_tone,
    )


def result_from_search_row(row) -> SearchResult:
    (url, title, snippet, score, posted_at, start_date, end_date, category,
     _target, _keywords, _code, _name, _kind, _dept, *rest) = row
    summary = rest[0] if rest else None
    figures = row[17] if len(row) > 17 else []
    return SearchResult(
        url=url, title=title, snippet=snippet, score=_score(score),
        posted_at=_iso(posted_at), start_date=_iso(start_date), end_date=_iso(end_date),
        category=category, summary=summary,
        related_images=related_figures(figures, snippet or ""),
    )
