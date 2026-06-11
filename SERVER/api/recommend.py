"""홈 추천공지·마감 임박 점수 계산 (임베딩·DB 무의존, 결정적).

test_streamlit/pages/home.py의 _score_notice 로직을 이식한다.
입력은 db.get_documents가 반환하는 row 튜플. 컬럼 순서는 거기서 SELECT한 순서를 따른다:
  [0]url [1]title [2]content [3]posted_at [4]start_date [5]end_date
  [6]category [7]target [8]keywords [9]code [10]name [11]kind [12]department [13]summary
"""
from datetime import date


def _strlist(x) -> list[str]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x]
    if isinstance(x, str):
        return [s.strip() for s in x.split(",") if s.strip()]
    return []


def _to_date(x):
    if x is None or isinstance(x, date):
        return x
    if hasattr(x, "date"):  # datetime
        return x.date()
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _row_fields(row) -> dict:
    """row 튜플에서 점수·표시에 필요한 필드만 추출."""
    return {
        "url": row[0],
        "title": row[1] or "",
        "content": row[2] or "",
        "end_date": _to_date(row[5]),
        "category": row[6],
        "target": _strlist(row[7]),
        "keywords": _strlist(row[8]),
        "department": row[12],
        "summary": (row[13] if len(row) > 13 else None) or "",
    }


def score_notice(
    f: dict,
    interests: list[str],
    major: str | None,
    year: int | None,
    today: date,
) -> tuple[int, list[str]]:
    """관심키워드 매칭 + 학과 일치 + 학년 + 마감 임박도로 점수 산출.

    반환: (score, matched_keywords)
    """
    score = 0
    haystack = f"{f['title']} {f['summary'] or f['content']}".lower()
    notice_kws = f["keywords"]

    matched: list[str] = []
    for kw in interests:
        if not kw:
            continue
        if kw in notice_kws or kw.lower() in haystack:
            matched.append(kw)
    score += len(matched) * 10

    if major and f["department"] == major:
        score += 5

    target = f["target"]
    if year and f"{year}학년" in target:
        score += 3
    if "전체" in target:
        score += 1

    end_date = f["end_date"]
    if end_date:
        days_left = (end_date - today).days
        if 0 <= days_left <= 14:
            # 가까울수록 부스트 (14→0점, 0→5점)
            score += max(0, 5 - days_left // 3)

    return score, matched


def _d_label(end_date, today: date) -> str | None:
    if not end_date:
        return None
    delta = (end_date - today).days
    if delta == 0:
        return "D-DAY"
    return f"D-{delta}" if delta > 0 else f"D+{-delta}"


def _trim(text: str, n: int = 120) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:n] + "…" if len(text) > n else text


def build_home(
    rows,
    interests: list[str],
    major: str | None,
    year: int | None,
    today: date | None = None,
) -> dict:
    """추천 3건 + 마감 임박 5건을 계산해 dict로 반환.

    - 추천: 만료 안 된 공지 중 score>0 상위 3건 (점수 내림차순)
    - 마감: end_date가 오늘~30일 이내인 공지 상위 5건 (마감일 오름차순)
    """
    today = today or date.today()
    fields = [_row_fields(r) for r in rows]
    alive = [f for f in fields if not (f["end_date"] and f["end_date"] < today)]

    scored = []
    for f in alive:
        s, matched = score_notice(f, interests, major, year, today)
        if s > 0:
            scored.append((s, f, matched))
    scored.sort(key=lambda x: x[0], reverse=True)

    recommended = [
        {
            "title": f["title"],
            "url": f["url"],
            "summary": _trim(f["summary"] or f["content"]),
            "category": f["category"],
            "d_label": _d_label(f["end_date"], today),
            "days_left": (f["end_date"] - today).days if f["end_date"] else None,
            "matched_keywords": matched[:2],
        }
        for _s, f, matched in scored[:3]
    ]

    upcoming = [
        f for f in alive
        if f["end_date"] and 0 <= (f["end_date"] - today).days <= 30
    ]
    upcoming.sort(key=lambda f: f["end_date"])
    deadlines = [
        {
            "title": f["title"],
            "url": f["url"],
            "category": f["category"],
            "end_date": f["end_date"].isoformat(),
            "d_label": _d_label(f["end_date"], today),
            "days_left": (f["end_date"] - today).days,
        }
        for f in upcoming[:5]
    ]

    return {"recommended": recommended, "deadlines": deadlines}
