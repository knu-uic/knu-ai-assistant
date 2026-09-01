import pytest

from sync.counseling import _has_system_button, _select_topics, _topics


class _Locator:
    def __init__(self, value="", exists=True, checked=None, selector=""):
        self.value = value
        self.exists = exists
        self.checked = checked
        self.selector = selector

    def count(self):
        return 1 if self.exists else 0

    def text_content(self):
        return self.value

    def check(self):
        self.checked.append(self.selector)


class _TopicFrame:
    def __init__(self):
        self.checked = []
        self.labels = {"#G2.ONE_NM0": "학업", "#G2.TWO_NM0": "진로상담"}

    def locator(self, selector):
        if selector in self.labels:
            return _Locator(value=self.labels[selector])
        return _Locator(exists=False, checked=self.checked, selector=selector)


def test_counseling_topics_are_read_and_selected_by_visible_label():
    frame = _TopicFrame()

    assert _topics(frame) == ["학업", "진로상담"]
    _select_topics(frame, ["진로상담"])
    assert frame.checked == ["#G2.TWO0"]
    with pytest.raises(RuntimeError, match="지원하지 않는"):
        _select_topics(frame, ["없는 주제"])


def test_system_button_detection_ignores_stale_frames():
    class BrokenFrame:
        def locator(self, _selector):
            raise RuntimeError("frame reloaded")

    class ReadyFrame:
        def locator(self, selector):
            return _Locator(exists=selector.endswith("imgsys1\"]"))

    class Page:
        frames = [BrokenFrame(), ReadyFrame()]

    assert _has_system_button(Page()) is True
