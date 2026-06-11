"""api.recommend 점수·정렬 단위 테스트 (DB 무의존)."""
from datetime import date, timedelta

from api.recommend import build_home, score_notice

TODAY = date(2026, 6, 11)


def _row(url, title, *, content="", end_date=None, category="academic",
         target=None, keywords=None, department=None, summary=None):
    # get_documents SELECT 순서: url,title,content,posted_at,start_date,end_date,
    # category,target,keywords,code,name,kind,department,summary
    return (
        url, title, content, None, None, end_date,
        category, target or [], keywords or [], "code", "name", "kind",
        department, summary,
    )


def _fields(row):
    from api.recommend import _row_fields
    return _row_fields(row)


def test_interest_keyword_match_adds_10_each():
    f = _fields(_row("u1", "장학금 신청 안내", keywords=["장학금"]))
    score, matched = score_notice(f, ["장학금", "인턴"], None, None, TODAY)
    assert matched == ["장학금"]
    assert score == 10 + 1 * 0  # 키워드 1개 매칭 (target 없음)


def test_major_and_year_and_target_boost():
    f = _fields(_row("u2", "공지", department="컴퓨터공학과", target=["3학년", "전체"]))
    score, _ = score_notice(f, [], "컴퓨터공학과", 3, TODAY)
    assert score == 5 + 3 + 1  # 학과 + 학년 + 전체


def test_deadline_boost_closer_is_higher():
    near = _fields(_row("u3", "마감 임박", end_date=TODAY + timedelta(days=1)))
    far = _fields(_row("u4", "마감 멀음", end_date=TODAY + timedelta(days=13)))
    s_near, _ = score_notice(near, [], None, None, TODAY)
    s_far, _ = score_notice(far, [], None, None, TODAY)
    assert s_near > s_far


def test_build_home_ranks_and_filters_expired():
    rows = [
        _row("hit", "인턴 채용 공고", keywords=["인턴"], target=["전체"]),
        _row("expired", "지난 공지", keywords=["인턴"], end_date=TODAY - timedelta(days=1)),
        _row("nomatch", "관련없는 공지"),
    ]
    out = build_home(rows, ["인턴"], None, None, today=TODAY)
    rec_urls = [r["url"] for r in out["recommended"]]
    assert rec_urls == ["hit"]  # 만료·무매칭 제외, 매칭만


def test_build_home_deadlines_within_30_days_sorted():
    rows = [
        _row("d5", "A", end_date=TODAY + timedelta(days=5)),
        _row("d2", "B", end_date=TODAY + timedelta(days=2)),
        _row("d40", "C", end_date=TODAY + timedelta(days=40)),  # 30일 초과 제외
    ]
    out = build_home(rows, [], None, None, today=TODAY)
    assert [d["url"] for d in out["deadlines"]] == ["d2", "d5"]
    assert out["deadlines"][0]["d_label"] == "D-2"
