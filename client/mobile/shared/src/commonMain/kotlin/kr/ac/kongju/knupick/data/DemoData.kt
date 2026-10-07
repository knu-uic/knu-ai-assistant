package kr.ac.kongju.knupick.data

import kotlinx.serialization.json.Json

/** Explicit fixtures only: never mixed into a real server response. */
object DemoData {
    val profile = Profile("DEMO", "공주", "컴퓨터공학과", 3, listOf("장학금", "인턴"),
        listOf("데이터베이스 설계"), portal_linked = true, lms_linked = true)
    val notices = listOf(
        Notice("https://www.kongju.ac.kr", "2026학년도 2학기 장학금 신청 안내", summary = "장학금 신청 대상과 제출 서류를 확인하세요. 이 공지는 화면 테스트용 예시입니다.", category = "장학", source_name = "학생복지과", department = "공통", deadline_label = "데모 · D-3", target = listOf("재학생")),
        Notice("https://www.kongju.ac.kr", "컴퓨터공학과 취업 특강 안내", summary = "현직 개발자와 함께하는 취업 준비 특강입니다. 실제 학교 일정이 아닌 데모 자료입니다.", category = "취업(진로)", source_name = "컴퓨터공학과", department = "컴퓨터공학과"),
        Notice("https://www.kongju.ac.kr", "수강 신청 변경 기간 안내", summary = "학기 수강 계획을 확인하세요. 테스트용 예시입니다.", category = "수강", source_name = "학사지원과", department = "공통"),
    )
    val home = HomeData(notices.take(2).map { HomeNotice(it.title, it.url, it.summary, it.category, it.deadline_label) },
        listOf(HomeNotice(notices[0].title, notices[0].url, category = "장학", d_label = "데모 · D-3", end_date = "예시 일정")))
    val tasks = listOf(
        LmsTask(1, "assignment", "ERD와 릴레이션 설계 제출", "데이터베이스 설계", progress = 0),
        LmsTask(2, "quiz", "3주차 학습 확인", "운영체제", progress = 50),
        LmsTask(3, "assignment", "네트워크 실습 보고서", "컴퓨터네트워크", is_done = true),
    )
    val courses = listOf(LmsCourse(1, "데이터베이스 설계"), LmsCourse(2, "운영체제"), LmsCourse(3, "컴퓨터네트워크"))
    val timetable = Json.parseToJsonElement("""[{"rows":[
        ["교시","월요일","화요일","수요일","목요일","금요일"],
        ["1교시 주간: (09:00~09:50)","데이터베이스 설계(01 교수) 9공101","","운영체제(01 교수) 9공201","",""],
        ["2교시 주간: (10:00~10:50)","데이터베이스 설계(01 교수) 9공101","컴퓨터네트워크(01 교수) 9공301","","",""],
        ["3교시 주간: (11:00~11:50)","","컴퓨터네트워크(01 교수) 9공301","","운영체제(01 교수) 9공201",""]
    ]}]""")
    val portal = Json.decodeFromString<PortalData>("""{
        "graduation_credits":{"교양":{"계":{"기준":"30","취득":"30"}},"전공":{"계":{"기준":"60","취득":"42"}},"졸업학점계":{"기준":"130","취득":"96"}},
        "grade_distribution":{"grids":{"grades":{"title":"데모 성적 분포","columns":["등급","과목 수"],"rows":[["A+","6"],["A","8"],["B+","4"]]}}},
        "cumulative_grades":{"grids":{"semesters":{"title":"데모 학기별 성적","columns":["년도","학기","취득학점","평점"],"rows":[["2025","1","18","3.8"],["2025","2","18","4.0"],["2026","1","18","3.9"]]}}}
    }""")
    val account = LlmAccount("demo-account", "demo", "데모 개인 모델", "demo-model", true)
}
