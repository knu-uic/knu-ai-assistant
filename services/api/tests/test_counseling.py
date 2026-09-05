import pytest

from sync.counseling import _advisors, _counseling_frame_state, _find_counseling_form_frame, _has_portal_message, _has_system_button, _select_advisor, _select_slot, _select_topics, _slots, _text, _topics


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


class _SelectionFrame(_TopicFrame):
    def __init__(self):
        super().__init__()
        self.labels.update({
            '[id="G1.KOR_NM0"]': "교수 A",
            '[id="G1.DEPT_NM0"]': "컴퓨터공학과",
            '[id="G1.ON_CNSL0"]': "",
            '[id="G3.RESER_DT0"]': "2026-09-10",
            '[id="G3.TM0"]': "10:00 ~ 10:30",
            '[id="G3.OFF_CNSL0"]': "",
        })


def test_counseling_topics_are_read_and_selected_by_visible_label():
    frame = _TopicFrame()

    assert _topics(frame) == ["학업", "진로상담"]
    _select_topics(frame, ["진로상담"])
    assert frame.checked == ["G2.TWO0"]
    with pytest.raises(RuntimeError, match="지원하지 않는"):
        _select_topics(frame, ["없는 주제"])


def test_counseling_advisor_and_slot_are_selected_by_visible_values():
    frame = _SelectionFrame()

    assert _advisors(frame) == [{"name": "교수 A", "department": "컴퓨터공학과", "row": 0}]
    assert _slots(frame) == [{"date": "2026-09-10", "time": "10:00 ~ 10:30", "row": 0}]
    _select_advisor(frame, "교수 A")
    _select_slot(frame, "2026-09-10", "10:00 ~ 10:30")
    assert frame.checked == ["G1.ON_CNSL0", "G3.OFF_CNSL0"]


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


def test_portal_message_is_found_across_child_frames():
    class BodyLocator(_Locator):
        def inner_text(self, timeout):
            return "상담신청이 완료되었습니다."

    class Frame:
        def locator(self, _selector):
            return BodyLocator()

    class Page:
        frames = [Frame()]

    class Context:
        pages = [Page()]

    assert _has_portal_message(Context(), "상담신청이 완료되었습니다.") is True
