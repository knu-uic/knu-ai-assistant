package kr.ac.kongju.knupick.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kr.ac.kongju.knupick.AppController
import kr.ac.kongju.knupick.AppState
import kr.ac.kongju.knupick.data.*

@Composable internal fun AcademicScreen(state: AppState, controller: AppController, openUrl: (String) -> Unit) {
    var section by remember { mutableStateOf("시간표") }
    var showCompleted by remember { mutableStateOf(false) }
    var favoriteOnly by remember { mutableStateOf(false) }
    var courseFilter by remember { mutableStateOf<String?>(null) }
    var syncKind by remember { mutableStateOf<String?>(null) }
    var deletingTask by remember { mutableStateOf<LmsTask?>(null) }
    val timetable = remember(state.timetable) { weekTimetable(state.timetable) }
    val credits = remember(state.portal.graduation_credits) { parseCredits(state.portal.graduation_credits) }
    val distribution = remember(state.portal.grade_distribution) { parseGrades(state.portal.grade_distribution) }
    val grades = remember(state.portal.cumulative_grades) { parseGrades(state.portal.cumulative_grades) }
    syncKind?.let { kind -> SyncDialog(kind, state.busy, { password -> controller.sync(kind, password); syncKind = null }, { syncKind = null }) }
    deletingTask?.let { task -> AlertDialog(onDismissRequest = { deletingTask = null }, title = { Text("LMS 항목 삭제") },
        text = { Text("KNU 목록에서 '${task.title}' 항목을 삭제할까요? 학교 LMS의 과제나 제출 자료는 삭제하지 않습니다.") },
        confirmButton = { TextButton(onClick = { controller.deleteTask(task); deletingTask = null }) { Text("삭제") } },
        dismissButton = { TextButton(onClick = { deletingTask = null }) { Text("취소") } }) }
    if (section == "시간표") {
        Column(Modifier.fillMaxSize().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            PageTitle("학사", "포털과 LMS에 연동된 내 학교 생활입니다.")
            AcademicSections(section) { section = it }
            if (state.profile?.portal_syncing == true) Text(state.profile.sync_stage ?: "학사 정보 동기화 중…",
                color = Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            state.profile?.portal_sync_error?.let { Text("포털 동기화: $it", color = MaterialTheme.colorScheme.error,
                fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("주간 시간표", Modifier.weight(1f), fontSize = 18.sp, fontWeight = FontWeight.Bold)
                TextButton(onClick = { syncKind = "portal" }, enabled = !state.busy) { Text("포털 동기화", fontSize = 12.sp) }
            }
            if (timetable.rows.isEmpty()) Box(Modifier.weight(1f)) { EmptyAcademic("동기화된 시간표가 없습니다.") }
            else WeekCalendar(timetable, Modifier.weight(1f).fillMaxWidth())
            Text("수업을 누르면 과목·시간·강의실을 볼 수 있어요.", color = Muted, fontSize = 11.sp, maxLines = 1)
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { PageTitle("학사", "포털과 LMS에 연동된 내 학교 생활입니다.") }
        item { AcademicSections(section) { section = it } }
        if (state.profile?.portal_syncing == true) item { PickCard { Caption(state.profile.sync_stage ?: "학사 정보를 동기화하고 있습니다. 잠시 후 새로고침해주세요.") } }
        state.profile?.portal_sync_error?.let { error -> item { Caption("포털 동기화: $error") } }
        state.profile?.lms_sync_error?.let { error -> item { Caption("LMS 동기화: $error") } }
        item {
            OutlinedButton(onClick = { syncKind = if (section == "LMS") "lms" else "portal" }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text(if (section == "LMS") "LMS 다시 동기화" else "포털 다시 동기화")
            }
        }
        when (section) {
            "취득학점" -> {
                if (credits.isEmpty()) item { EmptyAcademic("동기화된 취득학점 자료가 없습니다.") }
                items(credits) { credit -> PickCard {
                    Text(credit.label, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        CreditValue("기준", credit.standard); CreditValue("취득", credit.taken); CreditValue("부족", credit.deficit)
                    }
                    val standard = credit.standard.toFloatOrNull() ?: 0f
                    val taken = credit.taken.toFloatOrNull() ?: 0f
                    if (standard > 0) LinearProgressIndicator(progress = { (taken / standard).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                } }
                item { Caption("부족학점은 기준학점에서 취득학점을 뺀 참고값입니다. 최종 졸업 충족 여부는 학교 포털과 담당 부서에서 확인하세요.") }
            }
            "성적" -> {
                if (distribution.isEmpty() && grades.isEmpty()) item { EmptyAcademic("동기화된 성적 자료가 없습니다.") }
                item { Text("나의 성적 분포", fontSize = 19.sp, fontWeight = FontWeight.Bold) }
                items(distribution) { grid -> GradeTable(grid) }
                item { Text("누적 성적", fontSize = 19.sp, fontWeight = FontWeight.Bold) }
                items(grades) { grid -> GradeTable(grid) }
            }
            "LMS" -> {
                item { PickCard {
                    Text("강의", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                    if (state.courses.isEmpty()) Caption("동기화된 강의가 없습니다.")
                    state.courses.forEach { course ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text(course.course_name, modifier = Modifier.weight(1f), fontSize = 14.sp)
                            TextButton(onClick = { controller.favorite(course.course_name) }, enabled = !state.busy) {
                                Text(if (course.course_name in state.profile?.favorite_courses.orEmpty()) "★ 관심" else "☆ 관심")
                            }
                        }
                    }
                } }
                item {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("완료 항목 표시", modifier = Modifier.weight(1f), fontSize = 13.sp)
                        Switch(showCompleted, { showCompleted = it })
                    }
                }
                item { Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(favoriteOnly, { favoriteOnly = !favoriteOnly }, label = { Text("관심 강의만") })
                    FilterChip(courseFilter == null, { courseFilter = null }, label = { Text("전체 강의") })
                    state.courses.forEach { course -> FilterChip(courseFilter == course.course_name, { courseFilter = course.course_name }, label = { Text(course.course_name) }) }
                } }
                val shown = state.tasks.filter { task ->
                    (showCompleted || !task.is_done) && (courseFilter == null || task.course_name == courseFilter) &&
                        (!favoriteOnly || task.course_name in state.profile?.favorite_courses.orEmpty())
                }
                if (shown.isEmpty()) item { EmptyAcademic("표시할 LMS 항목이 없습니다.") }
                items(shown, key = { it.id }) { task -> PickCard {
                    Row(verticalAlignment = Alignment.Top) {
                        Checkbox(task.is_done, { controller.taskDone(task) }, enabled = !state.busy)
                        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                            Text(task.title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                            Caption(task.course_name ?: "강의 정보 없음")
                            Tag(when (task.task_type) { "assignment" -> "과제"; "quiz" -> "퀴즈"; "lecture" -> "강의"; else -> task.task_type })
                            task.due_date?.let { Caption("마감: $it") }
                            task.progress?.let { Caption("진도 $it%") }
                            task.url?.let { url -> TextButton(onClick = { openUrl(url) }) { Text("LMS 원문 열기") } }
                            TextButton(onClick = { deletingTask = task }, enabled = !state.busy) { Text("KNU 목록에서 삭제", color = MaterialTheme.colorScheme.error) }
                        }
                    }
                } }
                item { Caption("체크박스는 KNU에서 관리하는 완료 표시입니다. LMS 과제 제출이나 학교 시스템의 수강 완료를 대신하지 않습니다.") }
            }
        }
    }
}

@Composable private fun CreditValue(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) { Caption(label); Text(value, fontSize = 23.sp, fontWeight = FontWeight.Bold, color = Blue) }
}
@Composable private fun AcademicSections(section: String, select: (String) -> Unit) {
    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf("시간표", "취득학점", "성적", "LMS").forEach { title ->
            FilterChip(section == title, { select(title) }, label = { Text(title) })
        }
    }
}

@Composable private fun EmptyAcademic(text: String) { PickCard { Caption(text); Caption("처음 로그인했다면 동기화가 끝난 뒤 새로고침해주세요.") } }

@Composable private fun GradeTable(grid: GradeGrid) {
    var selectedYear by remember(grid) { mutableStateOf<String?>(null) }
    val yearColumn = grid.columns.indexOfFirst { "년도" in it || "연도" in it }
    val years = if (yearColumn >= 0) grid.rows.mapNotNull { it.getOrNull(yearColumn) }.distinct().sorted() else emptyList()
    val shown = if (selectedYear == null || yearColumn < 0) grid.rows else grid.rows.filter { it.getOrNull(yearColumn) == selectedYear }
    PickCard {
        if (grid.title.isNotBlank()) Text(grid.title, fontWeight = FontWeight.Bold)
        if (years.size > 1) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selectedYear == null, { selectedYear = null }, label = { Text("전체 연도") })
            years.forEach { year -> FilterChip(selectedYear == year, { selectedYear = year }, label = { Text(year) }) }
        }
        // Preserve every server-provided column, including future portal fields.
        Column(Modifier.horizontalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row { grid.columns.forEach { Text(it, Modifier.width(108.dp).padding(6.dp), fontWeight = FontWeight.SemiBold, color = Blue, fontSize = 12.sp) } }
            shown.forEach { row ->
                HorizontalDivider()
                Row { grid.columns.indices.forEach { index -> Text(row.getOrNull(index).orEmpty(), Modifier.width(108.dp).padding(6.dp), fontSize = 13.sp) } }
            }
        }
        if (shown.isEmpty()) Caption("표시할 성적이 없습니다.")
        Caption("표는 좌우로 스크롤할 수 있습니다.")
    }
}

@Composable private fun SyncDialog(kind: String, busy: Boolean, confirm: (String?) -> Unit, dismiss: () -> Unit) {
    var password by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = dismiss, title = { Text(if (kind == "portal") "포털 다시 동기화" else "LMS 다시 동기화") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Caption(if (kind == "portal") "포털 비밀번호를 다시 입력해주세요. 비밀번호는 기기에 저장하지 않습니다." else "저장된 서버 세션을 사용합니다. 세션이 만료됐다면 포털 비밀번호를 입력해주세요.")
            OutlinedTextField(password, { password = it }, label = { Text("포털 비밀번호${if (kind == "lms") " (선택)" else ""}") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true)
            Caption("학교 포털 또는 LMS에 실제 동기화 요청을 보냅니다.")
        }
    }, confirmButton = { TextButton(onClick = { confirm(password.takeIf { it.isNotEmpty() }); password = "" }, enabled = !busy && (kind == "lms" || password.isNotEmpty())) { Text("동기화 시작") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("취소") } })
}
