import pytest

from sync.knuis_sync import parse_knuis_identity, parse_profile_data
from sync.portal_auth import parse_portal_identity, portal_login_error_message


class FakeFrame:
    def __init__(self, datasets):
        self.datasets = datasets

    def evaluate(self, _script, grid_id):
        return self.datasets.get(grid_id)


def test_profile_does_not_require_graduation_credits():
    frame = FakeFrame(
        {
            "F_SRCH": {
                "NM": ["장예원"],
                "SUST_NM": ["컴퓨터공학과"],
                "SYEAR": ["3학년"],
            }
        }
    )

    assert parse_profile_data(frame) == ("장예원", "컴퓨터공학과", 3)


@pytest.mark.parametrize(
    "profile",
    [
        {"NM": [""], "SUST_NM": ["컴퓨터공학과"], "SYEAR": ["3"]},
        {"NM": ["장예원"], "SUST_NM": [""], "SYEAR": ["3"]},
        {"NM": ["장예원"], "SUST_NM": ["컴퓨터공학과"], "SYEAR": [""]},
    ],
)
def test_profile_rejects_incomplete_dataset(profile):
    with pytest.raises(RuntimeError):
        parse_profile_data(FakeFrame({"F_SRCH": profile}))


def test_portal_home_identity_is_available_without_knuis():
    assert parse_portal_identity(
        "202203236",
        "한정우(202203236)님 환영합니다.",
        "컴퓨터공학과 / 학부생",
    ) == {
        "name": "한정우",
        "major": "컴퓨터공학과",
        "academic_status": "학부생",
    }


def test_portal_home_identity_rejects_another_student():
    with pytest.raises(RuntimeError):
        parse_portal_identity(
            "202203236",
            "다른사람(202600001)님 환영합니다.",
            "컴퓨터공학과 / 학부생",
        )


def test_portal_password_lock_dialog_becomes_actionable_message():
    message = portal_login_error_message(
        "비밀번호 오류횟수가 5회 이상입니다.\n 비밀번호 변경 후 다시 시도해주세요!"
    )

    assert "5회 이상" in message
    assert "비밀번호를 변경" in message


def test_knuis_header_identity_supports_graduate_status():
    assert parse_knuis_identity(
        "202102271",
        "장예원(202102271, 학부생(졸업)) 식물자원학과(주)",
    ) == {
        "name": "장예원",
        "major": "식물자원학과(주)",
        "academic_status": "학부생(졸업)",
    }
