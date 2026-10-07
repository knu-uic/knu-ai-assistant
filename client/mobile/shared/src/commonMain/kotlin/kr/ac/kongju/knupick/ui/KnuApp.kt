package kr.ac.kongju.knupick.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kr.ac.kongju.knupick.AppController
import kr.ac.kongju.knupick.AppState
import kr.ac.kongju.knupick.data.*
import kotlinx.coroutines.launch

internal val Blue = Color(0xFF15539C)
internal val Ink = Color(0xFF14253F)
internal val Muted = Color(0xFF65748B)
internal val Soft = Color(0xFFE8F1FB)
internal val Background = Color(0xFFF4F7FB)
private val LocalOpenMenu = staticCompositionLocalOf<(() -> Unit)?> { null }
private val scheme = lightColorScheme(primary = Blue, onPrimary = Color.White,
    primaryContainer = Soft, onPrimaryContainer = Blue, background = Background,
    secondary = Blue, onSecondary = Color.White, secondaryContainer = Soft, onSecondaryContainer = Blue,
    surface = Color.White, onSurface = Ink, onBackground = Ink,
    outline = Color(0xFFE2E8F1), error = Color(0xFFD23B4A))

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KnuApp(controller: AppController, openUrl: (String) -> Unit) {
    val state by controller.state.collectAsState()
    var tab by rememberSaveable(state.authenticated) { mutableStateOf(0) }
    var serverDialog by remember { mutableStateOf(false) }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val uiScope = rememberCoroutineScope()
    LaunchedEffect(tab, state.authenticated, state.demo) { controller.setChatVisible(state.authenticated && !state.demo && tab == 2) }
    DisposableEffect(controller) { onDispose { controller.setChatVisible(false) } }
    MaterialTheme(colorScheme = scheme, shapes = Shapes(medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(24.dp))) {
        if (serverDialog) ServerDialog(controller) { serverDialog = false }
        if (!state.authenticated) {
            LoginScreen(state, controller, { serverDialog = true })
        } else {
            ModalNavigationDrawer(drawerState = drawer, gesturesEnabled = true,
                scrimColor = Color.Black.copy(alpha = .25f), drawerContent = {
                    ModalDrawerSheet(drawerState = drawer, modifier = Modifier.width(288.dp), drawerContainerColor = Color.White) {
                        Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            BrandMark(36)
                            Text("KNU PICK", modifier = Modifier.weight(1f), fontSize = 19.sp, fontWeight = FontWeight.ExtraBold, color = Blue)
                            IconButton(onClick = { uiScope.launch { drawer.close() } }, modifier = Modifier.semantics { contentDescription = "메뉴 닫기" }) { PickIcon(6) }
                        }
                        Column(Modifier.padding(horizontal = 20.dp, vertical = 4.dp)) { Caption("공주대학교 학생 어시스턴트") }
                        Spacer(Modifier.height(22.dp))
                        listOf("홈", "공지", "AI 대화", "학사", "내 정보").forEachIndexed { i, label ->
                            NavigationDrawerItem(selected = tab == i,
                                onClick = { tab = i; uiScope.launch { drawer.close() } },
                                icon = { PickIcon(i) }, label = { Text(label) },
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 3.dp),
                                colors = NavigationDrawerItemDefaults.colors(selectedContainerColor = Soft,
                                    selectedIconColor = Blue, selectedTextColor = Blue))
                        }
                        Spacer(Modifier.weight(1f))
                        Column(Modifier.padding(20.dp)) { Caption("왼쪽에서 밀어 열고\n왼쪽으로 밀거나 바깥을 눌러 닫으세요.") }
                    }
                }) {
                CompositionLocalProvider(LocalOpenMenu provides { uiScope.launch { drawer.open() } }) {
                    Scaffold(containerColor = Background, contentWindowInsets = WindowInsets.safeDrawing) { padding ->
                        Column(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding)) {
                            Box(Modifier.fillMaxWidth().height(3.dp)) {
                                if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                            }
                            if (state.demo) Caption("데모 · 실제 학교 자료 아님")
                            Feedback(state, controller::dismissMessage)
                            when (tab) {
                                0 -> HomeScreen(state, { tab = 1 }, { tab = 2 }, { tab = 3 }, openUrl)
                                1 -> NoticeScreen(state, controller, openUrl)
                                2 -> ChatScreen(state, controller, { tab = 4 })
                                3 -> AcademicScreen(state, controller, openUrl)
                                else -> SettingsScreen(state, controller, { serverDialog = true }, openUrl)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable internal fun BrandMark(size: Int = 48) {
    Box(Modifier.size(size.dp).clip(RoundedCornerShape((size / 3).dp)).background(Blue), contentAlignment = Alignment.Center) {
        Text("K", color = Color.White, fontSize = (size * .58).sp, fontWeight = FontWeight.Black)
    }
}

@Composable internal fun MenuButton() {
    val open = LocalOpenMenu.current ?: return
    IconButton(onClick = open, modifier = Modifier.semantics { contentDescription = "메뉴 열기" }) { PickIcon(5) }
}

@Composable internal fun PageTitle(title: String, subtitle: String, showMenu: Boolean = true) {
    Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (showMenu) MenuButton()
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(title, fontSize = 27.sp, fontWeight = FontWeight.Bold, color = Ink)
            Text(subtitle, fontSize = 13.sp, color = Muted, lineHeight = 20.sp)
        }
    }
}

@Composable internal fun PickCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color.White),
        border = BorderStroke(1.dp, Color(0xFFEEF2F7)), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
    }
}

@Composable internal fun Caption(text: String) { Text(text, fontSize = 12.sp, color = Muted, lineHeight = 19.sp) }
@Composable internal fun Tag(text: String, danger: Boolean = false) {
    Text(text, color = if (danger) MaterialTheme.colorScheme.error else Blue, fontSize = 11.sp,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(if (danger) Color(0xFFFDECEE) else Soft).padding(horizontal = 9.dp, vertical = 5.dp))
}

@Composable private fun Feedback(state: AppState, dismiss: () -> Unit) {
    val text = state.error ?: state.message ?: return
    Row(Modifier.fillMaxWidth().background(if (state.error != null) Color(0xFFFDECEE) else Soft).padding(start = 16.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(text, modifier = Modifier.weight(1f), fontSize = 12.sp, maxLines = 4, overflow = TextOverflow.Ellipsis,
            color = if (state.error != null) MaterialTheme.colorScheme.error else Blue)
        TextButton(onClick = dismiss) { Text("닫기") }
    }
}

@Composable private fun LoginScreen(state: AppState, controller: AppController, serverSettings: () -> Unit) {
    var studentId by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().background(Background).safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(26.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)) {
        Spacer(Modifier.height(28.dp))
        BrandMark(64)
        Text("학교 생활에 필요한 정보,\nKNU PICK 하나로.", fontSize = 30.sp, lineHeight = 42.sp, fontWeight = FontWeight.Bold)
        Caption("내 학과 공지부터 시간표와 과제까지.\n공주대학교 포털 계정으로 시작하세요.")
        PickCard {
            Text("포털 로그인", fontWeight = FontWeight.Bold, fontSize = 20.sp)
            OutlinedTextField(studentId, { studentId = it }, label = { Text("학번") }, singleLine = true,
                enabled = !state.busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(password, { password = it }, label = { Text("포털 비밀번호") }, singleLine = true,
                enabled = !state.busy, visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), modifier = Modifier.fillMaxWidth())
            Button(onClick = { controller.login(studentId, password); password = "" },
                enabled = !state.busy && studentId.isNotBlank() && password.isNotEmpty(), modifier = Modifier.fillMaxWidth().height(50.dp)) {
                Text(if (state.busy) "요청 처리 중…" else "로그인", fontWeight = FontWeight.Bold)
            }
            Caption("비밀번호는 기기에 저장하지 않습니다. 최초 로그인과 학사 동기화에는 시간이 걸릴 수 있습니다.")
        }
        Feedback(state, controller::dismissMessage)
        OutlinedButton(onClick = controller::testConnection, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text("서버 연결 테스트") }
        Caption("로컬 서버 연결 시 Android의 ‘주변 기기’ 권한이 필요할 수 있습니다. 연결 테스트는 학번·비밀번호를 전송하지 않습니다.")
        OutlinedButton(onClick = controller::demo, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text("계정 없이 데모 둘러보기") }
        TextButton(onClick = serverSettings, enabled = !state.busy, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("서버 연결 설정") }
        Caption("연결 서버: ${controller.serverUrl}")
        if (controller.serverUrl.startsWith("http:")) Caption("개발용 HTTP 연결입니다. 신뢰할 수 있는 로컬 환경에서만 사용하세요.")
    }
}

@Composable private fun ServerDialog(controller: AppController, dismiss: () -> Unit) {
    var url by remember { mutableStateOf(controller.serverUrl) }
    AlertDialog(onDismissRequest = dismiss, title = { Text("서버 연결 설정") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("주소 변경 시 이 기기의 로그인과 표시 중인 대화를 비웁니다. 서버에 저장된 기록은 삭제되지 않습니다.", fontSize = 13.sp)
            OutlinedTextField(url, { url = it }, label = { Text("KNU API 서버 주소") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            Caption(if (controller.allowLocalHttp) "Android 에뮬레이터에서 이 Mac에 연결: http://10.0.2.2:8000\n실제 기기: Mac의 사설 IP 또는 HTTPS 주소" else "배포 빌드는 HTTPS 연결만 지원합니다.")
        }
    }, confirmButton = { TextButton(onClick = { controller.configureServer(url); if (controller.serverUrl == runCatching { normalizeServerUrl(url, controller.allowLocalHttp) }.getOrNull()) dismiss() }) { Text("저장") } },
        dismissButton = { TextButton(onClick = dismiss) { Text("취소") } })
}

@Composable private fun HomeScreen(state: AppState, notices: () -> Unit, chat: () -> Unit, academic: () -> Unit, openUrl: (String) -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                MenuButton()
                BrandMark(44)
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text("KNU PICK", fontWeight = FontWeight.ExtraBold, fontSize = 23.sp, color = Blue)
                    Caption("공주대학교 학생 어시스턴트")
                }
            }
        }
        item { PageTitle("${state.profile?.name ?: "학생"}님, 안녕하세요", listOfNotNull(state.profile?.major, state.profile?.year?.let { "${it}학년" }).joinToString(" · ").ifEmpty { "오늘의 학교 생활을 확인하세요." }, showMenu = false) }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = Blue), shape = RoundedCornerShape(20.dp)) {
                Column(Modifier.fillMaxWidth().padding(22.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("궁금한 학교 정보,\nAI에게 물어보세요", color = Color.White, fontSize = 23.sp, lineHeight = 32.sp, fontWeight = FontWeight.Bold)
                    Text("내 학과 공지와 학사 정보를 함께 찾아드려요.", color = Color(0xFFC9DFF7), fontSize = 12.sp)
                    Button(onClick = chat, colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Blue)) { Text("AI 대화 시작") }
                }
            }
        }
        item { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("나를 위한 공지", fontSize = 19.sp, fontWeight = FontWeight.Bold); TextButton(onClick = notices) { Text("전체 보기") }
        } }
        if (state.home.recommended.isEmpty()) item { PickCard { Caption("추천 공지가 아직 없습니다. 내 정보에서 관심사를 선택해보세요.") } }
        items(state.home.recommended.take(5)) { n -> PickCard(Modifier.clickable { openUrl(n.url) }) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { n.category?.let { Tag(it) }; n.d_label?.let { Tag(it, (n.days_left ?: 99) <= 3) } }
            Text(n.title, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            n.summary?.let { Text(it, color = Muted, fontSize = 13.sp, maxLines = 2, overflow = TextOverflow.Ellipsis) }
        } }
        item { Text("다가오는 마감", fontSize = 19.sp, fontWeight = FontWeight.Bold) }
        if (state.home.deadlines.isEmpty()) item { Caption("다가오는 마감 일정이 없습니다.") }
        items(state.home.deadlines.take(5)) { n -> PickCard(Modifier.clickable { openUrl(n.url) }) {
            n.d_label?.let { Tag(it, (n.days_left ?: 99) <= 3) }; Text(n.title, fontWeight = FontWeight.SemiBold); n.end_date?.let { Caption("마감 $it") }
        } }
        item { OutlinedButton(onClick = academic, modifier = Modifier.fillMaxWidth()) { Text("시간표 · 성적 · LMS 확인") } }
        if (state.profile?.portal_syncing == true) item { Caption(state.profile.sync_stage ?: "포털 자료를 동기화하고 있습니다. 잠시 후 새로고침해주세요.") }
    }
}

@Composable private fun NoticeScreen(state: AppState, controller: AppController, openUrl: (String) -> Unit) {
    var search by remember { mutableStateOf("") }
    val shown = state.notices.filter { search.isBlank() || it.title.contains(search, true) || it.summary.orEmpty().contains(search, true) }
    var selected by remember { mutableStateOf<Notice?>(null) }
    selected?.let { n -> AlertDialog(onDismissRequest = { selected = null }, title = { Text(n.title, fontSize = 19.sp) },
        text = { Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Caption(listOfNotNull(n.source_name, n.department, n.posted_at).joinToString(" · "))
            Text(n.content?.takeIf { it.isNotBlank() } ?: n.summary ?: "본문은 원문에서 확인해주세요.", fontSize = 14.sp, lineHeight = 23.sp)
            if (n.target.isNotEmpty()) Caption("대상: ${n.target.joinToString(", ")}")
        } }, confirmButton = { TextButton(onClick = { openUrl(n.url) }) { Text("학교 원문 열기") } },
        dismissButton = { TextButton(onClick = { selected = null }) { Text("닫기") } }) }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { PageTitle("공지", "내 학과와 공통 공지를 확인하세요.") }
        item { OutlinedTextField(search, { search = it }, modifier = Modifier.fillMaxWidth(), singleLine = true, label = { Text("불러온 공지에서 검색") }) }
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("전체", "장학", "수강", "취업(진로)", "행사(공모전)", "일반(기타)").forEach { category ->
                    FilterChip(selected = state.category == category.takeUnless { it == "전체" }, enabled = !state.busy,
                        onClick = { controller.notices(category.takeUnless { it == "전체" }) }, label = { Text(category) })
                }
            }
        }
        if (shown.isEmpty()) item { PickCard { Caption(if (state.busy) "공지를 불러오고 있습니다." else "해당 공지가 없습니다.") } }
        items(shown) { n -> PickCard(Modifier.clickable { selected = n }) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(n.source_name ?: "학교 공지", color = Blue, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                n.deadline_label?.let { Tag(it, n.deadline_tone in listOf("danger", "warning")) }
            }
            Text(n.title, fontWeight = FontWeight.Bold, fontSize = 16.sp, lineHeight = 24.sp)
            Text(n.summary ?: n.content.orEmpty(), fontSize = 13.sp, color = Muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Caption(listOfNotNull(n.category, n.department, n.posted_at).joinToString(" · "))
        } }
        if (state.cursor != null) item { OutlinedButton(onClick = { controller.notices(state.category, true) }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text("공지 더 불러오기") } }
        item { Caption("검색은 현재 불러온 공지에만 적용됩니다. 학년·접수 상태 필터는 서버 API 확장 후 지원할 수 있습니다.") }
    }
}

@Composable private fun ChatScreen(state: AppState, controller: AppController, settings: () -> Unit) {
    var question by remember { mutableStateOf("") }
    var submitted by remember { mutableStateOf<String?>(null) }
    var historyOpen by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<ConversationSummary?>(null) }
    LaunchedEffect(question) { controller.setChatDraftActive(question.isNotBlank()) }
    DisposableEffect(controller) { onDispose { controller.setChatDraftActive(false) } }
    LaunchedEffect(state.busy, state.error, state.messages.size) {
        val pending = submitted
        if (!state.busy && pending != null) {
            if (state.messages.takeLast(2).firstOrNull() == ChatMessage("user", pending.trim()) &&
                state.messages.lastOrNull()?.role == "assistant" && state.error == null) question = ""
            submitted = null // Keep the input on failure, so retry does not require retyping.
        }
    }
    if (historyOpen) AlertDialog(onDismissRequest = { historyOpen = false }, title = { Text("서버 대화 기록") }, text = {
        Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Caption("같은 학생 계정의 KNU 웹·앱에서 공유합니다. Codmes 기록은 포함하지 않습니다.")
            TextButton(onClick = { controller.loadHistory() }, enabled = !state.busy) { Text("목록 새로고침") }
            if (state.conversations.isEmpty()) Caption(if (state.demo) "데모 모드는 서버에 기록을 저장하지 않습니다." else "서버에 저장된 대화가 없습니다.")
            state.conversations.forEach { conversation -> Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { controller.openConversation(conversation); historyOpen = false }, enabled = !state.busy && !state.unsavedHistory, modifier = Modifier.weight(1f)) { Text(conversation.title, maxLines = 2) }
                TextButton(onClick = { deleting = conversation }, enabled = !state.busy && !state.unsavedHistory) { Text("삭제", color = MaterialTheme.colorScheme.error) }
            } }
            if (state.historyCursor != null) TextButton(onClick = { controller.loadHistory(true) }, enabled = !state.busy) { Text("기록 더 불러오기") }
        }
    }, confirmButton = { TextButton(onClick = { historyOpen = false }) { Text("닫기") } })
    deleting?.let { conversation -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("대화 기록 삭제") },
        text = { Text("서버에서 이 대화를 삭제하면 KNU 웹과 다른 기기에서도 사라집니다. 삭제할까요?") },
        confirmButton = { TextButton(onClick = { controller.deleteConversation(conversation); deleting = null }) { Text("삭제") } },
        dismissButton = { TextButton(onClick = { deleting = null }) { Text("취소") } }) }
    val ready = state.demo || if (state.chatSource == "school") state.school.available else state.accounts.any { it.active && it.model.isNotEmpty() }
    Column(Modifier.fillMaxSize().imePadding()) {
        Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                MenuButton()
                Text("AI 대화", modifier = Modifier.weight(1f), fontSize = 25.sp, fontWeight = FontWeight.Bold)
                Row { TextButton(onClick = { historyOpen = true; controller.loadHistory() }, enabled = !state.busy) { Text("기록") }
                    TextButton(onClick = controller::clearChat, enabled = !state.busy && !state.unsavedHistory) { Text("새 대화") } }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(state.chatSource == "school", { controller.chatSource("school") }, label = { Text("학교 제공 모델") }, enabled = !state.busy)
                FilterChip(state.chatSource == "personal", { controller.chatSource("personal") }, label = { Text("내 개인 모델") }, enabled = !state.busy)
            }
            if (!ready) {
                Caption(if (state.chatSource == "school") "서버에 학교 제공 모델이 설정되지 않았습니다." else "내 정보에서 개인 계정을 연결하고 모델을 선택해주세요.")
                TextButton(onClick = settings) { Text("모델 설정으로 이동") }
            } else Caption(if (state.chatSource == "school") state.school.model else state.accounts.firstOrNull { it.active }?.model ?: "데모 모델")
            Text(if (state.demo) "데모 대화 · 서버에 저장되지 않습니다" else state.historySyncIssue ?: "웹·앱 기록 자동 동기화 · 약 2초 간격",
                color = Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (state.unsavedHistory) {
                Caption("답변은 받았지만 서버 저장에 실패했습니다. 저장 전 앱을 종료하면 이 답변을 잃을 수 있습니다.")
                Row { TextButton(onClick = { controller.retryHistory() }, enabled = !state.busy) { Text("다시 저장") }
                    TextButton(onClick = { controller.retryHistory(true) }, enabled = !state.busy) { Text("새 대화로 저장") } }
            }
        }
        val scroll = androidx.compose.foundation.lazy.rememberLazyListState()
        var followLatest by remember { mutableStateOf(true) }
        LaunchedEffect(scroll) {
            snapshotFlow { scroll.isScrollInProgress to
                ((scroll.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= scroll.layoutInfo.totalItemsCount - 2) }
                .collect { (scrolling, atBottom) -> if (scrolling) followLatest = atBottom }
        }
        LaunchedEffect(state.conversationId) {
            followLatest = true
            if (state.messages.isNotEmpty()) scroll.scrollToItem(state.messages.lastIndex)
        }
        LaunchedEffect(state.messages.size) {
            if (followLatest && state.messages.isNotEmpty()) scroll.animateScrollToItem(state.messages.lastIndex)
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), state = scroll, contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            if (state.messages.isEmpty()) item { PickCard {
                Text("무엇이 궁금한가요?", fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Caption("학교 공지와 내 학사 정보에 대해 물어보세요. AI 답변의 중요한 내용은 학교 원문과 함께 확인하세요.")
                listOf("내 학과 장학금 정보를 알려줘", "이번 학기 시간표를 알려줘", "LMS 미완료 과제를 정리해줘").forEach { value ->
                    OutlinedButton(onClick = { question = value }, modifier = Modifier.fillMaxWidth()) { Text(value, fontSize = 12.sp) }
                }
            } }
            itemsIndexed(state.messages, key = { index, message -> "${state.conversationId ?: "new"}:$index:${message.role}" }) { _, message ->
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = if (message.role == "user") Soft else Color.White), shape = RoundedCornerShape(16.dp)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                        Text(if (message.role == "user") "나" else "KNU PICK", color = Blue, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        androidx.compose.foundation.text.selection.SelectionContainer { Text(message.content, fontSize = 14.sp, lineHeight = 23.sp) }
                    }
                }
            }
            if (state.busy) item { Caption("답변을 준비하고 있습니다…") }
        }
        Row(Modifier.fillMaxWidth().background(Color.White).padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(question, { if (it.length <= 10000) { question = it; controller.setChatDraftActive(it.isNotBlank()) } }, modifier = Modifier.weight(1f),
                placeholder = { Text("학교 정보 물어보기", fontSize = 13.sp) }, maxLines = 4, enabled = !state.busy)
            Button(onClick = { submitted = question; controller.ask(question) }, enabled = ready && !state.busy && !state.unsavedHistory && question.isNotBlank()) { Text("전송") }
        }
    }
}
