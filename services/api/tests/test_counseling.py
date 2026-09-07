import pytest
import sync.counseling as counseling

from sync.counseling import _advisor_entries, _advisor_name, _advisors, _counseling_frame_state, _fill_title_and_content, _find_counseling_form_frame, _has_portal_message, _has_system_button, _select_advisor, _select_mode, _select_slot, _select_topics, _slot_date, _slot_time, _slots, _text, _topics


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

    def dblclick(self):
        self.checked.append(self.selector.removeprefix('[id="').removesuffix('"]'))

    def click(self):
        return None

    def fill(self, value):
        self.value = value

class _TopicFrame:
    def __init__(self):
        self.checked = []
        self.labels = {
            '[id="G2.ONE_NM0"]': "학업",
            '[id="G2.TWO_NM0"]': "진로상담",
        }

    def locator(self, selector):
        if selector in self.labels:
            return _Locator(value=self.labels[selector], checked=self.checked, selector=selector)
        return _Locator(exists=False, checked=self.checked, selector=selector)

    def evaluate(self, script, value):
        if "SetRowNo" in script:
            return None
        self.checked.append(value)
        return True


class _SelectionFrame(_TopicFrame):
    def __init__(self):
        super().__init__()
        self.labels.update({
            "#T1ItemRoot > label:nth-child(2) > div > div": "",
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


def test_counseling_advisor_mode_and_slot_are_selected_by_visible_values():
    frame = _SelectionFrame()

    assert _advisors(frame) == [{"name": "교수 A", "department": "컴퓨터공학과", "row": 0}]
    assert _slots(frame) == [{"date": "2026-09-10", "time": "10:00 ~ 10:30", "row": 0}]
    _select_advisor(frame, "교수 A")
    _select_mode(frame, "visit")
    _select_slot(frame, "2026-09-10", "10:00 ~ 10:30")
    assert frame.checked == ["G1.KOR_NM0", "G1.OFF_CNSL0", "G3.OFF_CNSL0"]


def test_visit_mode_and_slots_use_the_selected_professor_and_full_grid():
    frame = _SelectionFrame()
    frame.labels.update({
        '[id="G1.KOR_NM1"]': "교수 B",
        '[id="G1.OFF_CNSL1"]': "",
        '[id="G3.RESER_DT46"]': "2026-10-07",
        '[id="G3.TM46"]': "16:00 ~ 16:30",
        '[id="G3.OFF_CNSL46"]': "",
    })

    _select_mode(frame, "visit", advisor_row=1)
    _select_slot(frame, "2026-10-07", "16:00 ~ 16:30")

    assert frame.checked == ["G1.OFF_CNSL1", "G3.OFF_CNSL46"]


def test_slots_use_the_grid_data_when_virtual_scrolling_hides_rows():
    class VirtualGridFrame(_SelectionFrame):
        def evaluate(self, _script, value=None):
            if value is None:
                return [
                    {"date": "2026-09-10", "time": "10:00 ~ 10:30", "row": 0},
                    {"date": "20261007", "time": "16:00 ~ 16:30", "row": 46},
                ]
            return super().evaluate(_script, value)

    assert _slots(VirtualGridFrame())[-1] == {
        "date": "2026-10-07", "time": "16:00 ~ 16:30", "row": 46
    }


def test_counseling_advisors_include_and_select_mentor_tab():
    frame = _SelectionFrame()
    frame.labels.update({
        "#T1ItemRoot > label:nth-child(8) > div > div": "",
        '[id="G4.KOR_NM0"]': "김동근",
        '[id="G4.DEPT_NM0"]': "컴퓨터공학과",
    })

    assert _advisor_entries(frame) == [
        {"name": "교수 A", "department": "컴퓨터공학과", "row": 0, "group": "G1"},
        {"name": "김동근", "department": "컴퓨터공학과", "row": 0, "group": "G4"},
    ]
    _select_advisor(frame, "김동근")
    assert frame.checked == ["G4.KOR_NM0"]


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


def test_counseling_title_uses_webcrea_visible_input_not_hidden_cell():
    class Frame:
        def __init__(self):
            self.title_input = _Locator()

        def locator(self, selector):
            if selector == '[id="F1.CNSL_TTL_my_inputBox"]':
                return self.title_input
            if selector == "#F1 > table > tbody > tr:nth-child(7) > td.mi75 > div > div":
                return _Locator()
            return _Locator(exists=False)

    class Keyboard:
        value = ""

        def insert_text(self, value):
            self.value = value

    class Page:
        keyboard = Keyboard()

    frame, page = Frame(), Page()
    _fill_title_and_content(frame, page, "제목", "내용")
    assert frame.title_input.value == "제목"
    assert page.keyboard.value == "내용"


def test_counseling_advisor_name_removes_only_portal_honorifics():
    assert _advisor_name(" 서영정 교수님 ") == "서영정"
    assert _advisor_name("서영정 교수") == "서영정"


def test_counseling_slot_values_accept_chat_date_and_time_formats():
    assert _slot_date("2026년 9월 8일") == "2026-09-08"
    assert _slot_time("16:00~16:30") == "16:00 ~ 16:30"


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

    assert _counseling_frame_state(Context()) == "WorkFrame:header=1,search=0"


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


def test_submission_is_verified_from_the_portal_inquiry_grid(monkeypatch):
    class DateField:
        def click(self):
            return None

        def press(self, _key):
            return None

        def type(self, _value):
            return None

    class Frame:
        def locator(self, _selector):
            return DateField()

        def evaluate(self, _script):
            if "Boolean" in _script:
                return True
            return {
                "CNSL_TTL": ["테스트 제목"],
                "ASK_CTNT": ["테스트 내용"],
                "KOR_NM": ["서영정"],
                "CNSL_DTTM": ["20260908"],
                "CNSL_TYPE_CD": ["G4B001"],
            }

    class Locator:
        def count(self):
            return 1

    class Page:
        def locator(self, _selector):
            return Locator()

    class Context:
        pages = [Page()]

    frame = Frame()
    monkeypatch.setattr(counseling, "open_menu", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(counseling, "_find_inquiry_frame", lambda *_args: frame)
    monkeypatch.setattr(counseling, "_webcrea_click", lambda *_args: None)
    assert counseling._has_submitted_counseling(
        Context(), "서영정 교수님", "visit", "2026년 9월 8일", "테스트 제목", "테스트 내용"
    )
