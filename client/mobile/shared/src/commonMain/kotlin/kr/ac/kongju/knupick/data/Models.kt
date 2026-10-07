package kr.ac.kongju.knupick.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable data class LoginRequest(val student_id: String, val password: String)
@Serializable data class TokenResponse(val access_token: String)
@Serializable data class Profile(
    val student_id: String? = null, val name: String? = null, val major: String? = null,
    val year: Int? = null, val interests: List<String> = emptyList(),
    val favorite_courses: List<String> = emptyList(), val portal_linked: Boolean = false,
    val portal_syncing: Boolean = false, val sync_stage: String? = null,
    val portal_sync_error: String? = null, val lms_sync_error: String? = null,
    val lms_linked: Boolean = false,
)
@Serializable data class Notice(
    val url: String, val title: String, val content: String? = null,
    val summary: String? = null, val posted_at: String? = null,
    val category: String? = null, val target: List<String> = emptyList(),
    val source_name: String? = null, val department: String? = null,
    val deadline_label: String? = null, val deadline_tone: String? = null,
)
@Serializable data class NoticePage(val notices: List<Notice> = emptyList(), val next_cursor: String? = null)
@Serializable data class HomeNotice(
    val title: String, val url: String, val summary: String? = null,
    val category: String? = null, val d_label: String? = null,
    val days_left: Int? = null, val end_date: String? = null,
    val matched_keywords: List<String> = emptyList(),
)
@Serializable data class HomeData(
    val recommended: List<HomeNotice> = emptyList(), val deadlines: List<HomeNotice> = emptyList(),
)
@Serializable data class TimetableResponse(val timetable: JsonElement? = null)
@Serializable data class PortalData(
    val grade_distribution: JsonObject? = null, val cumulative_grades: JsonObject? = null,
    val graduation_credits: JsonObject? = null,
)
@Serializable data class LmsTask(
    val id: Int, val task_type: String, val title: String, val course_name: String? = null,
    val due_date: String? = null, val progress: Int? = null, val url: String? = null,
    val is_done: Boolean = false,
)
@Serializable data class TaskPage(val tasks: List<LmsTask> = emptyList())
@Serializable data class LmsCourse(val course_id: Int, val course_name: String)
@Serializable data class CoursePage(val courses: List<LmsCourse> = emptyList())
@Serializable data class LlmAccount(
    val id: String, val provider: String, val label: String, val model: String = "", val active: Boolean = false,
)
@Serializable data class AccountPage(val items: List<LlmAccount> = emptyList())
@Serializable data class ModelPage(val models: List<String> = emptyList())
@Serializable data class SchoolModel(val available: Boolean = false, val model: String = "")
@Serializable data class ChatModels(val school: SchoolModel = SchoolModel())
@Serializable data class ChatMessage(val role: String, val content: String)
@Serializable data class ChatRequest(val question: String, val history: List<ChatMessage>, val source: String)
@Serializable data class ChatResponse(val answer: String, val conversation: Conversation? = null, val context: JsonObject? = null)
@Serializable data class ChatTurnRequest(val question: String, val source: String,
    val conversation_id: String, val revision: Int, val request_id: String)
@Serializable data class CodexLogin(
    val id: String, val user_code: String, val verification_url: String, val interval: Int = 5,
)
@Serializable data class CodexStatus(val status: String, val account: LlmAccount? = null)
@Serializable data class SyncStart(val job_id: String)
@Serializable data class SyncStatus(
    val status: String, val step: String? = null, val detail: String? = null,
    val needs_reconnect: Boolean = false, val result: JsonElement? = null,
)
@Serializable data class ConversationSummary(
    val id: String, val title: String, val source: String, val revision: Int,
    val created_at: String, val updated_at: String,
)
@Serializable data class Conversation(
    val id: String, val title: String, val source: String, val revision: Int,
    val created_at: String, val updated_at: String, val messages: List<ChatMessage>,
) {
    fun summary() = ConversationSummary(id, title, source, revision, created_at, updated_at)
}
@Serializable data class ConversationPage(val items: List<ConversationSummary> = emptyList(), val next_cursor: String? = null)
@Serializable data class ConversationCreate(val id: String, val title: String, val source: String, val messages: List<ChatMessage>)
@Serializable data class ConversationUpdate(val title: String, val source: String, val messages: List<ChatMessage>, val revision: Int)
