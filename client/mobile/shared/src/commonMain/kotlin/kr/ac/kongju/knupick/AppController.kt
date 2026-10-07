package kr.ac.kongju.knupick

import kr.ac.kongju.knupick.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.json.JsonElement
import kotlin.uuid.Uuid

data class AppState(
    val authenticated: Boolean = false, val demo: Boolean = false,
    val busy: Boolean = false, val error: String? = null, val message: String? = null,
    val profile: Profile? = null, val home: HomeData = HomeData(),
    val notices: List<Notice> = emptyList(), val cursor: String? = null, val category: String? = null,
    val timetable: JsonElement? = null, val portal: PortalData = PortalData(),
    val tasks: List<LmsTask> = emptyList(), val courses: List<LmsCourse> = emptyList(),
    val accounts: List<LlmAccount> = emptyList(), val school: SchoolModel = SchoolModel(),
    val models: Map<String, List<String>> = emptyMap(), val chatSource: String = "school",
    val messages: List<ChatMessage> = emptyList(), val codexLogin: CodexLogin? = null,
    val conversations: List<ConversationSummary> = emptyList(), val historyCursor: String? = null,
    val conversationId: String? = null, val conversationRevision: Int? = null,
    val unsavedHistory: Boolean = false, val conversationSource: String = "school",
    val historySyncIssue: String? = null,
)

class AppController(val api: KnuApi, val allowLocalHttp: Boolean) {
    private var scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var codexJob: Job? = null
    private var historyJob: Job? = null
    private var foreground = false
    private var closed = false
    private var chatVisible = false
    private var chatDraftActive = false
    private var stateEpoch = 0L
    private var openLatestOnEntry = true
    private var historyHeadIds = emptySet<String>()
    private val mutableState = MutableStateFlow(AppState(authenticated = !api.store.token.isNullOrBlank()))
    val state = mutableState.asStateFlow()
    val serverUrl get() = api.store.serverUrl

    init { if (state.value.authenticated) refresh() }

    private fun action(block: suspend () -> Unit) {
        if (state.value.busy) return
        val actionEpoch = ++stateEpoch // Discard an older background read, even after this action completes.
        mutableState.update { it.copy(busy = true, error = null, message = null) }
        scope.launch {
            try { block() }
            catch (e: CancellationException) { throw e }
            catch (e: Throwable) {
                if (closed || actionEpoch != stateEpoch) return@launch
                if (e is ApiException && e.status == 401) {
                    api.store.token = null
                    codexJob?.cancel()
                    mutableState.value = AppState(error = "세션이 만료되었습니다. 다시 로그인해주세요.")
                } else mutableState.update { it.copy(error = e.userMessage()) }
            } finally {
                if (!closed && actionEpoch == stateEpoch) { mutableState.update { it.copy(busy = false) }; startHistorySync() }
            }
        }
    }

    fun setForeground(active: Boolean) {
        foreground = active
        if (!active) { historyJob?.cancel(); historyJob = null }
        else startHistorySync()
    }
    fun setChatVisible(visible: Boolean) {
        chatVisible = visible
        if (!visible) { historyJob?.cancel(); historyJob = null }
        else startHistorySync()
    }
    fun setChatDraftActive(active: Boolean) { chatDraftActive = active }
    private fun startHistorySync() {
        if (closed || !foreground || !chatVisible || !state.value.authenticated || state.value.demo || historyJob?.isActive == true) return
        historyJob = scope.launch {
            var waitMillis = 2000L
            while (isActive) {
                if (!state.value.busy && !state.value.unsavedHistory) {
                    val epoch = stateEpoch
                    val token = api.store.token
                    val server = serverUrl
                    try {
                        syncHistorySilently()
                        waitMillis = 2000L
                    } catch (e: CancellationException) { throw e }
                    catch (e: Throwable) {
                        if (epoch != stateEpoch || token != api.store.token || server != serverUrl || !foreground || !chatVisible) {
                            delay(2000L)
                            continue
                        }
                        if (e is ApiException && e.status == 401) {
                            resetSession()
                            mutableState.value = AppState(error = "세션이 만료되었습니다. 다시 로그인해주세요.")
                            return@launch
                        }
                        // No full-screen loading, transcript clearing, or repeated error banners.
                        mutableState.update { it.copy(historySyncIssue = if (e is ApiException && e.status == 403)
                            e.userMessage() else "자동 연결 재시도 중 · 기존 대화는 유지됩니다") }
                        waitMillis = if (e is ApiException && e.status == 429) 30000L else (waitMillis * 2).coerceAtMost(30000L)
                    }
                }
                delay(waitMillis)
            }
        }
    }
    private suspend fun syncHistorySilently() {
        val before = state.value
        val epoch = stateEpoch
        val token = api.store.token
        val server = serverUrl
        fun stillCurrent() = foreground && chatVisible && epoch == stateEpoch && token == api.store.token &&
            server == serverUrl && !state.value.busy && !state.value.unsavedHistory
        val page = api.conversations()
        if (!stillCurrent()) return
        val selected = before.conversationId
        val latest = if (selected == null && openLatestOnEntry && !chatDraftActive && before.messages.isEmpty()) page.items.firstOrNull() else null
        val summary = page.items.firstOrNull { it.id == selected }
        val readId = latest?.id ?: selected?.takeIf { summary == null || summary.revision != before.conversationRevision }
        var deleted = false
        val saved = if (readId == null) null else try { api.conversation(readId) }
            catch (e: ApiException) { if (e.status != 404) throw e; deleted = true; null }
        if (!stillCurrent() || (latest != null && chatDraftActive)) return
        val previous = state.value
        val expanded = previous.conversations.any { it.id !in historyHeadIds }
        val ids = page.items.map { it.id }.toSet()
        val tail = if (expanded && page.next_cursor != null)
            previous.conversations.filter { it.id !in historyHeadIds && it.id !in ids && (!deleted || it.id != readId) } else emptyList()
        historyHeadIds = ids
        if (latest != null && saved != null) openLatestOnEntry = false
        mutableState.update { current ->
            current.copy(conversations = page.items + tail,
                historyCursor = if (tail.isNotEmpty()) current.historyCursor else page.next_cursor,
                messages = saved?.messages ?: if (deleted && selected == readId) emptyList() else current.messages,
                conversationId = saved?.id ?: if (deleted && selected == readId) null else current.conversationId,
                conversationRevision = saved?.revision ?: if (deleted && selected == readId) null else current.conversationRevision,
                chatSource = saved?.source ?: current.chatSource, conversationSource = saved?.source ?: current.conversationSource,
                historySyncIssue = null)
        }
    }

    fun dismissMessage() { mutableState.update { it.copy(error = null, message = null) } }
    fun configureServer(url: String) {
        try {
            val normalized = normalizeServerUrl(url, allowLocalHttp)
            if (normalized != api.store.serverUrl) {
                resetSession()
                api.store.serverUrl = normalized
                mutableState.update { it.copy(message = "서버 주소를 저장했습니다. 변경한 서버에 다시 로그인해주세요.") }
            }
        } catch (e: Throwable) { mutableState.update { it.copy(error = e.userMessage()) } }
    }
    fun login(studentId: String, password: String) = action {
        require(studentId.isNotBlank() && password.isNotEmpty()) { "학번과 비밀번호를 입력해주세요." }
        api.store.serverUrl = normalizeServerUrl(api.store.serverUrl, allowLocalHttp)
        val token = api.login(studentId, password)
        require(token.isNotBlank()) { "서버에서 로그인 토큰을 받지 못했습니다." }
        api.store.token = token
        mutableState.update { it.copy(authenticated = true, demo = false) }
        loadAll()
    }
    fun testConnection() = action {
        api.store.serverUrl = normalizeServerUrl(api.store.serverUrl, allowLocalHttp)
        api.health()
        mutableState.update { it.copy(message = "KNU 서버에 연결됐습니다. 포털 로그인을 진행해주세요.") }
    }
    fun demo() {
        resetSession()
        mutableState.value = AppState(authenticated = true, demo = true,
            profile = DemoData.profile, home = DemoData.home, notices = DemoData.notices,
            timetable = DemoData.timetable, portal = DemoData.portal,
            tasks = DemoData.tasks, courses = DemoData.courses, accounts = listOf(DemoData.account),
            school = SchoolModel(true, "데모 모델"))
    }
    private fun resetSession() {
        stateEpoch++
        scope.cancel()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
        codexJob = null
        historyJob = null
        historyHeadIds = emptySet()
        openLatestOnEntry = true
        chatDraftActive = false
        api.store.token = null
        mutableState.value = AppState()
    }
    fun logout() {
        val oldToken = api.store.token
        val url = api.store.serverUrl
        val wasDemo = state.value.demo
        resetSession() // Clear UI and token even if revocation fails offline.
        if (!wasDemo && oldToken != null) scope.launch {
            val capturedStore = MemorySessionStore(url).apply { token = oldToken }
            try { KnuApi(api.client, capturedStore).logout() }
            catch (e: CancellationException) { throw e }
            catch (_: Throwable) { mutableState.update { it.copy(message = "앱에서 로그아웃했습니다. 서버 세션 해제는 연결 실패로 확인하지 못했습니다.") } }
        }
    }
    fun refresh() = action { if (state.value.demo) delay(150) else loadAll() }
    private suspend fun loadAll() {
        val profile = api.profile()
        mutableState.update { it.copy(profile = profile) }
        val errors = mutableListOf<String>()
        suspend fun load(label: String, block: suspend () -> Unit) {
            try { block() }
            catch (e: CancellationException) { throw e }
            catch (e: ApiException) { if (e.status == 401) throw e else errors.add("$label: ${e.userMessage()}") }
            catch (e: Throwable) { errors.add("$label: ${e.userMessage()}") }
        }
        load("홈") { val v = api.home(); mutableState.update { it.copy(home = v) } }
        load("공지") { val v = api.notices(state.value.category); mutableState.update { it.copy(notices = v.notices, cursor = v.next_cursor) } }
        load("시간표") { val v = api.timetable(); mutableState.update { it.copy(timetable = v.timetable) } }
        load("포털") { val v = api.portal(); mutableState.update { it.copy(portal = v) } }
        load("LMS") { val v = api.tasks(); mutableState.update { it.copy(tasks = v.tasks) } }
        load("과목") { val v = api.courses(); mutableState.update { it.copy(courses = v.courses) } }
        load("개인 모델") { val v = api.accounts(); mutableState.update { it.copy(accounts = v.items) } }
        load("학교 모델") {
            val v = api.chatModels()
            mutableState.update { it.copy(school = v.school,
                chatSource = if (it.conversationId != null) it.chatSource else if (v.school.available) "school" else "personal") }
        }
        load("대화 기록") {
            val v = api.conversations(); mutableState.update { it.copy(conversations = v.items, historyCursor = v.next_cursor) }
            historyHeadIds = v.items.map { it.id }.toSet()
            refreshCurrentHistory()
        }
        if (errors.isNotEmpty()) mutableState.update { it.copy(error = errors.joinToString("\n")) }
    }
    fun notices(category: String?, append: Boolean = false) = action {
        if (state.value.demo) {
            mutableState.update { it.copy(category = category, notices = DemoData.notices.filter { n -> category == null || n.category == category }) }
        } else {
            val cursor = if (append) state.value.cursor else null
            if (append && cursor == null) return@action
            val page = api.notices(category, cursor)
            mutableState.update { it.copy(category = category, cursor = page.next_cursor,
                notices = if (append) (it.notices + page.notices).distinctBy { n -> n.url } else page.notices) }
        }
    }
    fun chatSource(source: String) {
        if (source in listOf("school", "personal") && !state.value.busy) mutableState.update { it.copy(chatSource = source) }
    }
    fun clearChat() {
        if (state.value.unsavedHistory) { mutableState.update { it.copy(error = "아직 서버에 저장되지 않은 대화가 있습니다. 먼저 기록을 저장해주세요.") }; return }
        if (!state.value.busy) {
            stateEpoch++
            openLatestOnEntry = false
            mutableState.update { it.copy(messages = emptyList(), conversationId = null, conversationRevision = null) }
        }
    }
    fun ask(question: String) = action {
        openLatestOnEntry = false
        val q = question.trim()
        require(q.isNotEmpty() && q.length <= 10000) { "질문은 1자 이상 10,000자 이하로 입력해주세요." }
        require(!state.value.unsavedHistory) { "저장되지 않은 대화 기록을 먼저 저장해주세요." }
        require(state.value.messages.size < 10000) { "대화 원본의 저장 한도에 도달했습니다. 새 대화를 시작해주세요." }
        if (!state.value.demo && state.value.conversationRevision != null) {
            val latest = api.conversation(state.value.conversationId!!)
            if (latest.revision != state.value.conversationRevision) throw ApiException(409, "다른 기기에서 대화가 변경됐습니다. 대화 목록에서 다시 열어주세요.")
        }
        val before = state.value.messages
        val revision = state.value.conversationRevision ?: 0
        val id = state.value.conversationId ?: Uuid.random().toString()
        mutableState.update { it.copy(messages = before + ChatMessage("user", q)) }
        try {
            val result = if (state.value.demo) {
                delay(400)
                ChatResponse("[데모 답변] 실제 AI나 학교 서버를 호출하지 않았습니다. 공지 탭에서 장학·수강·취업 공지 화면을 확인하고, 학사 탭에서 시간표·성적·LMS 예시를 살펴보세요. 실제 답변은 서버와 모델을 연결한 뒤 사용할 수 있습니다.")
            } else api.chat(q, id, revision, Uuid.random().toString(), state.value.chatSource)
            val saved = result.conversation
            mutableState.update { it.copy(messages = saved?.messages ?: (it.messages + ChatMessage("assistant", result.answer)),
                unsavedHistory = !it.demo && saved == null, conversationSource = it.chatSource,
                conversationId = if (it.demo) null else saved?.id ?: id, conversationRevision = saved?.revision,
                conversations = if (saved == null) it.conversations else listOf(saved.summary()) + it.conversations.filter { c -> c.id != saved.id }) }
            if (!state.value.demo && saved == null) throw ApiException(502, "답변은 받았지만 서버의 저장 확인이 없습니다. 받은 기록을 저장한 뒤 다시 시도해주세요.")
        } catch (e: Throwable) {
            if (!state.value.unsavedHistory) {
                // A response can be lost after the server committed. Recover that UUID
                // instead of blindly replaying the question or overwriting the history.
                val saved = if (e !is CancellationException && !state.value.demo) runCatching { api.conversation(id) }.getOrNull() else null
                mutableState.update { it.copy(messages = saved?.messages ?: before,
                    conversationId = saved?.id ?: it.conversationId,
                    conversationRevision = saved?.revision ?: it.conversationRevision,
                    chatSource = saved?.source ?: it.chatSource, conversationSource = saved?.source ?: it.conversationSource,
                    conversations = if (saved == null) it.conversations else listOf(saved.summary()) + it.conversations.filter { c -> c.id != saved.id }) }
                if (saved != null && saved.revision > revision && saved.messages.takeLast(2).firstOrNull() == ChatMessage("user", q) &&
                    saved.messages.lastOrNull()?.role == "assistant") {
                    mutableState.update { it.copy(message = "연결이 끊겼지만 서버에 저장된 답변을 복원했습니다.") }
                    return@action
                }
            }
            throw e
        }
    }
    private suspend fun persistHistory(asNew: Boolean = false) {
        val current = state.value
        val id = if (asNew) Uuid.random().toString() else current.conversationId ?: Uuid.random().toString()
        if (current.conversationId == null || asNew) mutableState.update { it.copy(conversationId = id, conversationRevision = null) }
        val title = current.messages.firstOrNull { it.role == "user" }?.content?.take(100) ?: "새 대화"
        val saved = api.saveConversation(id, title, current.conversationSource, current.messages,
            if (asNew) null else current.conversationRevision)
        mutableState.update { it.copy(conversationId = saved.id, conversationRevision = saved.revision,
            unsavedHistory = false, conversations = (listOf(saved.summary()) + it.conversations.filter { c -> c.id != saved.id })) }
    }
    fun retryHistory(asNew: Boolean = false) = action { if (state.value.unsavedHistory) persistHistory(asNew) }
    fun loadHistory(append: Boolean = false) = action {
        if (state.value.demo) return@action
        val page = api.conversations(if (append) state.value.historyCursor else null)
        if (!append) historyHeadIds = page.items.map { it.id }.toSet()
        mutableState.update { it.copy(conversations = if (append) (it.conversations + page.items).distinctBy { c -> c.id } else page.items, historyCursor = page.next_cursor) }
        if (!append) refreshCurrentHistory()
    }
    private suspend fun refreshCurrentHistory() {
        if (state.value.unsavedHistory) return
        val id = state.value.conversationId ?: return
        val saved = try { api.conversation(id) } catch (e: ApiException) {
            if (e.status != 404) throw e
            mutableState.update { it.copy(messages = emptyList(), conversationId = null, conversationRevision = null,
                message = "서버에서 삭제된 대화입니다. 새 대화를 시작할 수 있습니다.") }
            return
        }
        mutableState.update { it.copy(messages = saved.messages, conversationRevision = saved.revision,
            chatSource = saved.source, conversationSource = saved.source) }
    }
    fun openConversation(summary: ConversationSummary) = action {
        openLatestOnEntry = false
        require(!state.value.unsavedHistory) { "현재 대화의 저장되지 않은 기록을 먼저 저장해주세요." }
        val conversation = api.conversation(summary.id)
        mutableState.update { it.copy(messages = conversation.messages, conversationId = conversation.id,
            conversationRevision = conversation.revision, chatSource = conversation.source, conversationSource = conversation.source) }
    }
    fun deleteConversation(summary: ConversationSummary) = action {
        require(!state.value.unsavedHistory) { "저장되지 않은 기록을 먼저 저장해주세요." }
        api.deleteConversation(summary.id, summary.revision)
        mutableState.update { it.copy(conversations = it.conversations.filter { c -> c.id != summary.id },
            messages = if (it.conversationId == summary.id) emptyList() else it.messages,
            conversationId = if (it.conversationId == summary.id) null else it.conversationId,
            conversationRevision = if (it.conversationId == summary.id) null else it.conversationRevision) }
    }
    fun saveInterests(values: List<String>) = action {
        require(values.size <= 6) { "관심사는 최대 6개까지 선택할 수 있습니다." }
        val profile = if (state.value.demo) state.value.profile!!.copy(interests = values) else api.interests(values)
        mutableState.update { it.copy(profile = profile, message = "관심사를 저장했습니다.") }
    }
    fun favorite(course: String) = action {
        val selected = state.value.profile?.favorite_courses.orEmpty()
        val values = if (course in selected) selected - course else selected + course
        val profile = if (state.value.demo) state.value.profile!!.copy(favorite_courses = values) else api.favorites(values)
        mutableState.update { it.copy(profile = profile) }
    }
    fun taskDone(task: LmsTask) = action {
        if (!state.value.demo) api.taskDone(task.id, !task.is_done)
        mutableState.update { it.copy(tasks = it.tasks.map { value -> if (value.id == task.id) value.copy(is_done = !task.is_done) else value }) }
    }
    fun deleteTask(task: LmsTask) = action {
        if (!state.value.demo) api.deleteTask(task.id)
        mutableState.update { it.copy(tasks = it.tasks.filter { value -> value.id != task.id }) }
    }
    fun loadModels(account: LlmAccount) = action {
        val models = if (state.value.demo) listOf("demo-model") else api.accountModels(account.id).models
        mutableState.update { it.copy(models = it.models + (account.id to models)) }
    }
    fun selectModel(account: LlmAccount, model: String) = action {
        if (!state.value.demo) api.selectModel(account.id, model)
        mutableState.update { it.copy(accounts = it.accounts.map { a -> a.copy(active = a.id == account.id, model = if (a.id == account.id) model else a.model) }, message = "개인 대화 모델을 선택했습니다.") }
    }
    fun addKey(provider: String, key: String) = action {
        require(!state.value.demo) { "데모 모드에서는 실제 API 키를 연결하지 않습니다." }
        require(key.trim().length in 20..500) { "API 키 형식을 확인해주세요." }
        api.addKey(provider, key)
        val accounts = api.accounts()
        mutableState.update { it.copy(accounts = accounts.items, message = "계정이 연결됐습니다. 사용할 모델을 선택해주세요.") }
    }
    fun removeAccount(account: LlmAccount) = action {
        if (!state.value.demo) api.removeAccount(account.id)
        mutableState.update { it.copy(accounts = it.accounts.filter { a -> a.id != account.id }, models = it.models - account.id) }
    }
    fun startCodex() = action {
        require(!state.value.demo) { "데모 모드에서는 실제 계정을 연결하지 않습니다." }
        codexJob?.cancel()
        val login = api.startCodex()
        mutableState.update { it.copy(codexLogin = login) }
        codexJob = scope.launch {
            try {
                withTimeout(900000) {
                    while (isActive) {
                        delay(maxOf(3, login.interval) * 1000L)
                        when (api.pollCodex(login.id).status) {
                            "approved" -> {
                                val accounts = api.accounts()
                                mutableState.update { it.copy(accounts = accounts.items, codexLogin = null,
                                    message = "Codex 계정이 연결됐습니다. 사용할 모델을 선택해주세요.") }
                                return@withTimeout
                            }
                            "expired" -> throw ApiException(408, "인증 시간이 만료되었습니다.")
                        }
                    }
                }
            } catch (_: TimeoutCancellationException) {
                mutableState.update { it.copy(codexLogin = null, error = "인증 시간이 만료되었습니다.") }
            } catch (e: CancellationException) { throw e }
            catch (e: Throwable) {
                if (e is ApiException && e.status == 401) {
                    api.store.token = null
                    mutableState.value = AppState(error = "세션이 만료되었습니다. 다시 로그인해주세요.")
                } else mutableState.update { it.copy(codexLogin = null, error = e.userMessage()) }
            }
        }
    }
    fun cancelCodex() { codexJob?.cancel(); mutableState.update { it.copy(codexLogin = null) } }
    fun sync(kind: String, password: String?) = action {
        if (state.value.demo) { mutableState.update { it.copy(message = "데모 자료입니다. 실제 동기화는 하지 않았습니다.") }; return@action }
        val studentId = state.value.profile?.student_id ?: throw IllegalArgumentException("먼저 로그인해주세요.")
        api.sync(kind, studentId, password) { step -> mutableState.update { it.copy(message = step) } }
        loadAll()
        mutableState.update { it.copy(message = "동기화를 완료했습니다.") }
    }
    fun close() { closed = true; foreground = false; historyJob?.cancel(); scope.cancel(); api.client.close() }
}
