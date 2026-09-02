import pytest

from sync.counseling import _counseling_frame_state, _find_counseling_form_frame, _has_system_button, _select_topics, _text, _topics


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

    def input_value(self):
        return self.value

    def get_attribute(self, _name):
        return self.value

class _TopicFrame:
    def __init__(self):
        self.checked = []
        self.labels = {
            '[id="G2.ONE_NM0"]': "학업",
            '[id="G2.TWO_NM0"]': "진로상담",
        }

    def locator(self, selector):
        if selector in self.labels:
            return _Locator(value=self.labels[selector])
        return _Locator(exists=False, checked=self.checked, selector=selector)

    def evaluate(self, _script, value):
        self.checked.append(value)
        return True


def test_counseling_topics_are_read_and_selected_by_visible_label():
    frame = _TopicFrame()

    assert _topics(frame) == ["학업", "진로상담"]
    _select_topics(frame, ["진로상담"])
    assert frame.checked == ["G2.TWO0"]
    with pytest.raises(RuntimeError, match="지원하지 않는"):
        _select_topics(frame, ["없는 주제"])


def test_counseling_text_reads_webcrea_input_value_when_text_is_empty():
    class InputOnlyLocator(_Locator):
        def text_content(self):
            return ""

    class Frame:
        def locator(self, _selector):
            return InputOnlyLocator(value="지도교수")

    assert _text(Frame(), '[id="G1.KOR_NM0"]') == "지도교수"


def test_counseling_text_skips_missing_selector_without_waiting_for_value():
    class MissingFrame:
        def locator(self, _selector):
            return _Locator(exists=False)

    assert _text(MissingFrame(), '[id="G1.KOR_NM0"]') == ""


def test_counseling_form_frame_uses_loaded_child_frame():
    class BlankFrame:
        def locator(self, _selector):
            return _Locator(exists=False)

    class FormFrame:
        def locator(self, _selector):
            return _Locator(exists=True)

    class Page:
        frames = [BlankFrame(), FormFrame()]

    class Context:
        pages = [Page()]

    assert isinstance(_find_counseling_form_frame(Context()), FormFrame)


def test_counseling_frame_state_contains_only_selector_counts():
    class Frame:
        name = "WorkFrame"

        def locator(self, selector):
            return _Locator(exists=selector == '[id="G1.Header"]')

    class Page:
        frames = [Frame()]

    class Context:
        pages = [Page()]

    assert _counseling_frame_state(Context()) == "WorkFrame:header=1,advisor=0"


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
