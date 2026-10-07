package kr.ac.kongju.knupick.data

import io.ktor.client.HttpClient
import io.ktor.client.request.*
import io.ktor.client.statement.bodyAsText
import io.ktor.http.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*

interface SessionStore {
    var serverUrl: String
    var token: String?
}

class MemorySessionStore(override var serverUrl: String = "https://localhost") : SessionStore {
    override var token: String? = null
}

class ApiException(val status: Int, message: String) : Exception(message)

/** LAN classification for Android's permission preflight, separate from HTTP policy. */
fun isLocalNetworkHost(input: String): Boolean {
    val host = input.lowercase().removePrefix("[").removeSuffix("]").trimEnd('.')
    val octets = host.split('.').map { it.toIntOrNull() }
    val ipv4 = octets.size == 4 && octets.all { it != null && it in 0..255 } &&
        (octets[0] == 10 || octets[0] == 127 ||
            (octets[0] == 192 && octets[1] == 168) || (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 169 && octets[1] == 254))
    return ipv4 || host == "localhost" || host.endsWith(".local") || host == "::1" ||
        (host.contains(':') && (host.startsWith("fc") || host.startsWith("fd") ||
            host.startsWith("fe8") || host.startsWith("fe9") || host.startsWith("fea") || host.startsWith("feb")))
}

/** No credentials in URLs, arbitrary base paths, or non-HTTP schemes. */
fun normalizeServerUrl(input: String, allowLocalHttp: Boolean): String {
    val url = try { Url(input.trim()) } catch (_: Exception) {
        throw IllegalArgumentException("서버 주소를 확인해주세요. 예: https://knu.example.com")
    }
    require(url.host.isNotBlank() && url.user.isNullOrBlank() && url.password.isNullOrBlank() &&
        url.parameters.isEmpty() && url.fragment.isBlank() && url.encodedPath in listOf("", "/", "/api", "/api/")) {
        "서버 주소에는 계정 정보, 쿼리 또는 /api 이외의 경로를 넣을 수 없습니다."
    }
    val octets = url.host.split('.').map { it.toIntOrNull() }
    val privateIpv4 = octets.size == 4 && octets.all { it != null && it in 0..255 } &&
        (octets[0] == 10 || octets[0] == 127 ||
            (octets[0] == 192 && octets[1] == 168) || (octets[0] == 172 && octets[1] in 16..31))
    val local = url.host in listOf("localhost", "::1", "[::1]") || privateIpv4
    require(url.protocol == URLProtocol.HTTPS || (allowLocalHttp && local && url.protocol == URLProtocol.HTTP)) {
        "HTTPS 주소를 사용해주세요. 개발 빌드에서는 로컬·사설 IP의 HTTP만 허용합니다."
    }
    return URLBuilder(url).apply { encodedPath = "" }.buildString().trimEnd('/')
}

class KnuApi(val client: HttpClient, val store: SessionStore) {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    private suspend inline fun <reified T> request(
        method: HttpMethod, path: String, body: String? = null,
        query: Map<String, String?> = emptyMap(), authenticated: Boolean = true,
    ): T {
        val response = client.request("${store.serverUrl}/api$path") {
            this.method = method
            contentType(ContentType.Application.Json)
            if (authenticated) store.token?.let { bearerAuth(it) }
            query.forEach { (key, value) -> if (value != null) parameter(key, value) }
            if (body != null) setBody(body)
        }
        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            val detail = runCatching {
                val value = json.parseToJsonElement(text).jsonObject["detail"]
                (value as? JsonPrimitive)?.contentOrNull
            }.getOrNull()
            throw ApiException(response.status.value, detail ?: "요청 실패 (${response.status.value})")
        }
        return json.decodeFromString<T>(text)
    }

    suspend fun login(studentId: String, password: String): String =
        request<TokenResponse>(HttpMethod.Post, "/auth/portal-login",
            json.encodeToString(LoginRequest(studentId.trim(), password)), authenticated = false).access_token
    suspend fun health() {
        val result = request<JsonObject>(HttpMethod.Get, "/health", authenticated = false)
        if (result["status"]?.jsonPrimitive?.contentOrNull != "ok")
            throw ApiException(503, "서버가 아직 준비되지 않았습니다.")
    }
    suspend fun logout() { request<JsonObject>(HttpMethod.Post, "/auth/logout") }
    suspend fun profile(): Profile = request(HttpMethod.Get, "/me")
    suspend fun home(): HomeData = request(HttpMethod.Get, "/me/home")
    suspend fun notices(category: String? = null, cursor: String? = null): NoticePage =
        request(HttpMethod.Get, "/notices", query = mapOf("limit" to "20", "category" to category, "cursor" to cursor))
    suspend fun timetable(): TimetableResponse = request(HttpMethod.Get, "/me/timetable")
    suspend fun portal(): PortalData = request(HttpMethod.Get, "/me/portal")
    suspend fun tasks(): TaskPage = request(HttpMethod.Get, "/me/lms/tasks")
    suspend fun courses(): CoursePage = request(HttpMethod.Get, "/me/lms/courses")
    suspend fun interests(values: List<String>): Profile = request(HttpMethod.Post, "/me/interests",
        buildJsonObject { put("interests", JsonArray(values.map(::JsonPrimitive))) }.toString())
    suspend fun favorites(values: List<String>): Profile = request(HttpMethod.Post, "/me/lms/favorites",
        buildJsonObject { put("favorite_courses", JsonArray(values.map(::JsonPrimitive))) }.toString())
    suspend fun taskDone(id: Int, done: Boolean) {
        // This endpoint intentionally returns 204, not JSON.
        val response = client.post("${store.serverUrl}/api/me/lms/tasks/$id/done") {
            store.token?.let { bearerAuth(it) }
            contentType(ContentType.Application.Json)
            setBody(buildJsonObject { put("is_done", done) }.toString())
        }
        if (!response.status.isSuccess()) throw ApiException(response.status.value, "완료 상태를 저장하지 못했습니다.")
    }
    suspend fun accounts(): AccountPage = request(HttpMethod.Get, "/me/llm/accounts")
    suspend fun deleteTask(id: Int) {
        val response = client.delete("${store.serverUrl}/api/me/lms/tasks/$id") {
            store.token?.let { bearerAuth(it) }
        }
        if (!response.status.isSuccess()) throw ApiException(response.status.value, "LMS 항목을 삭제하지 못했습니다.")
    }
    suspend fun chatModels(): ChatModels = request(HttpMethod.Get, "/chat/models")
    suspend fun accountModels(id: String): ModelPage = request(HttpMethod.Get, "/me/llm/accounts/${id.encodeURLPathPart()}/models")
    suspend fun selectModel(id: String, model: String): LlmAccount = request(HttpMethod.Put,
        "/me/llm/accounts/${id.encodeURLPathPart()}/selection", buildJsonObject { put("model", model) }.toString())
    suspend fun addKey(provider: String, key: String): LlmAccount {
        require(provider in listOf("openai", "google"))
        return request(HttpMethod.Post, "/me/llm/$provider-key", buildJsonObject { put("api_key", key.trim()) }.toString())
    }
    suspend fun removeAccount(id: String) { request<JsonObject>(HttpMethod.Delete, "/me/llm/accounts/${id.encodeURLPathPart()}") }
    suspend fun startCodex(): CodexLogin = request(HttpMethod.Post, "/me/llm/codex/login")
    suspend fun pollCodex(id: String): CodexStatus = request(HttpMethod.Get, "/me/llm/codex/login/${id.encodeURLPathPart()}")
    suspend fun chat(question: String, conversationId: String, revision: Int, requestId: String, source: String): ChatResponse {
        require(source in listOf("school", "personal"))
        require(question.isNotBlank() && question.length <= 10000)
        return request(HttpMethod.Post, "/chat", json.encodeToString(ChatTurnRequest(question, source, conversationId, revision, requestId)))
    }
    suspend fun conversations(cursor: String? = null): ConversationPage = request(HttpMethod.Get, "/me/conversations", query = mapOf("cursor" to cursor))
    suspend fun conversation(id: String): Conversation = request(HttpMethod.Get, "/me/conversations/${id.encodeURLPathPart()}")
    suspend fun saveConversation(id: String, title: String, source: String, messages: List<ChatMessage>, revision: Int?): Conversation =
        if (revision == null) request(HttpMethod.Post, "/me/conversations", json.encodeToString(ConversationCreate(id, title, source, messages)))
        else request(HttpMethod.Put, "/me/conversations/${id.encodeURLPathPart()}", json.encodeToString(ConversationUpdate(title, source, messages, revision)))
    suspend fun deleteConversation(id: String, revision: Int) {
        val response = client.delete("${store.serverUrl}/api/me/conversations/${id.encodeURLPathPart()}") {
            store.token?.let { bearerAuth(it) }; parameter("revision", revision)
        }
        if (!response.status.isSuccess()) throw ApiException(response.status.value,
            if (response.status.value == 409) "다른 기기에서 기록이 변경됐습니다. 목록을 새로 불러와주세요." else "대화 기록을 삭제하지 못했습니다.")
    }
    suspend fun sync(kind: String, studentId: String, password: String?, onStep: (String) -> Unit) {
        require(kind in listOf("portal", "lms"))
        val body = buildJsonObject {
            put("student_id", studentId)
            if (!password.isNullOrEmpty()) put("password", password)
        }.toString()
        val job = request<SyncStart>(HttpMethod.Post, "/$kind/sync/start", body)
        repeat(120) {
            val result = request<SyncStatus>(HttpMethod.Get, "/$kind/sync/${job.job_id.encodeURLPathPart()}")
            when (result.status) {
                "done" -> {
                    val payload = result.result as? JsonObject
                    if (payload?.get("success") == JsonPrimitive(false) || payload?.get("ok") == JsonPrimitive(false)) {
                        throw ApiException(409, payload["message"]?.jsonPrimitive?.content ?: "동기화에 실패했습니다.")
                    }
                    return
                }
                "failed" -> throw ApiException(409, result.detail ?: "동기화에 실패했습니다.")
                else -> onStep(result.step ?: "동기화 대기 중…")
            }
            delay(2000)
        }
        throw ApiException(408, "동기화 시간이 초과되었습니다. 잠시 후 새로고침해주세요.")
    }
}

fun Throwable.userMessage(): String = when (this) {
    is CancellationException -> throw this
    is ApiException, is IllegalArgumentException -> message ?: "요청에 실패했습니다."
    else -> "서버에 연결하지 못했습니다. 주소와 네트워크를 확인해주세요."
}
