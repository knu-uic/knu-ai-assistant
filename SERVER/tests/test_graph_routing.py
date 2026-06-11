"""router query_mode → 경로 매핑 단위 테스트."""
from retrieval.graph import _route_by_mode


def test_smalltalk_routes_to_smalltalk():
    assert _route_by_mode({"query_mode": "smalltalk"}) == "smalltalk"


def test_broad_routes_to_broad():
    assert _route_by_mode({"query_mode": "broad"}) == "broad"


def test_precise_routes_to_precise():
    assert _route_by_mode({"query_mode": "precise"}) == "precise"


def test_unknown_defaults_to_precise():
    assert _route_by_mode({}) == "precise"
