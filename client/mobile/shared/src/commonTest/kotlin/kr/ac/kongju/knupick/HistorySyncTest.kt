package kr.ac.kongju.knupick

import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.*
import io.ktor.http.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.Json
import kr.ac.kongju.knupick.data.*
import kotlin.test.*

@OptIn(ExperimentalCoroutinesApi::class)
class HistorySyncTest {
    private class Fixture {
        var saved = Conversation("conversation-id", "공유 대화", "school", 1, "2026-10-07", "2026-10-07",
            listOf(ChatMessage("user", "처음 질문"), ChatMessage("assistant", "처음 답변")))
        var headCalls = 0
        var readCalls = 0
        var status = HttpStatusCode.OK
        var deleted = false
        var headGate: CompletableDeferred<Unit>? = null
        var readGate: CompletableDeferred<Unit>? = null
        var readStatus = HttpStatusCode.OK
        val json = Json { encodeDefaults = true }
        val client = HttpClient(MockEngine(MockEngineConfig().apply {
          dispatcher = Dispatchers.Main
          addHandler { request ->
            val path = request.url.encodedPath
            val text = when (path) {
                "/api/me/conversations" -> {
                    headCalls++
                    headGate?.await()
                    if (status != HttpStatusCode.OK) return@addHandler respond("{}", status)
                    json.encodeToString(ConversationPage(if (deleted) emptyList() else listOf(saved.summary())))
                }
                "/api/me/conversations/conversation-id" -> {
                    readCalls++
                    val captured = saved
                    readGate?.await()
                    if (readStatus != HttpStatusCode.OK) return@addHandler respond("{}", readStatus)
                    if (deleted) return@addHandler respond("{}", HttpStatusCode.NotFound)
                    json.encodeToString(captured)
                }
                else -> "{}"
            }
            respond(text, headers = headersOf(HttpHeaders.ContentType, "application/json"))
          }
        }))
        val store = MemorySessionStore().apply { token = "test-student-token" }
        val controller = AppController(KnuApi(client, store), true)
        fun append() { saved = saved.copy(revision = saved.revision + 1,
            messages = saved.messages + listOf(ChatMessage("user", "웹의 새 질문"), ChatMessage("assistant", "웹의 새 답변"))) }
        fun show() { controller.setForeground(true); controller.setChatVisible(true) }
    }

    @Test fun changedTranscriptUpdatesSilentlyAndForegroundControlsPolling() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture()
        try {
            runCurrent()
            val initialCalls = f.headCalls
            f.controller.setChatVisible(true); runCurrent()
            assertEquals(initialCalls, f.headCalls) // Hidden app makes no poll requests.
            f.controller.setForeground(true); runCurrent()
            assertEquals(2, f.controller.state.value.messages.size)
            val before = f.controller.state.value
            val reads = f.readCalls
            advanceTimeBy(2000); runCurrent()
            assertSame(before, f.controller.state.value) // Equal state causes no emission/rebuild.
            assertEquals(reads, f.readCalls) // Revision unchanged: don't download the transcript.
            val seen = mutableListOf<AppState>()
            val observer = backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { f.controller.state.collect { seen += it } }
            f.append(); advanceTimeBy(2000); runCurrent()
            assertEquals(4, f.controller.state.value.messages.size)
            assertEquals("웹의 새 답변", f.controller.state.value.messages.last().content)
            assertTrue(seen.none { it.busy || it.messages.isEmpty() })
            assertNull(f.controller.state.value.error)
            f.controller.setForeground(false)
            val paused = f.headCalls
            advanceTimeBy(10000); runCurrent()
            assertEquals(paused, f.headCalls)
            f.append(); f.controller.setForeground(true); runCurrent()
            assertEquals(6, f.controller.state.value.messages.size) // Resume refresh is immediate.
            f.controller.setChatVisible(false)
            val hidden = f.headCalls
            advanceTimeBy(10000); runCurrent()
            assertEquals(hidden, f.headCalls)
            observer.cancel()
        } finally { f.controller.close(); Dispatchers.resetMain() }
    }

    @Test fun typingAndExplicitNewConversationAreNeverHijackedByLatestHistory() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture()
        try {
            runCurrent(); f.controller.setChatDraftActive(true); f.show(); runCurrent()
            assertNull(f.controller.state.value.conversationId)
            assertEquals(0, f.readCalls)
            assertEquals(1, f.controller.state.value.conversations.size)
            f.controller.setChatDraftActive(false); advanceTimeBy(2000); runCurrent()
            assertEquals(f.saved.id, f.controller.state.value.conversationId)
            f.controller.clearChat(); f.append(); advanceTimeBy(2000); runCurrent()
            assertNull(f.controller.state.value.conversationId)
            assertTrue(f.controller.state.value.messages.isEmpty())
        } finally { f.controller.close(); Dispatchers.resetMain() }
    }

    @Test fun oldReadAndOld401CannotReplaceNewConversationOrLogOutCurrentSession() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture()
        try {
            runCurrent(); f.show(); runCurrent()
            f.append(); val held = CompletableDeferred<Unit>(); f.readGate = held
            f.readStatus = HttpStatusCode.Unauthorized
            advanceTimeBy(2000); runCurrent()
            f.controller.clearChat() // User intent supersedes the in-flight poll.
            held.complete(Unit); runCurrent()
            assertTrue(f.controller.state.value.authenticated)
            assertEquals("test-student-token", f.store.token)
            assertTrue(f.controller.state.value.messages.isEmpty())
            assertNull(f.controller.state.value.error)
        } finally { f.controller.close(); Dispatchers.resetMain() }
    }

    @Test fun offlinePollPreservesTranscriptAndBacksOffWithoutGlobalErrorOrBusy() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture()
        try {
            runCurrent(); f.show(); runCurrent()
            val original = f.controller.state.value.messages
            f.status = HttpStatusCode.ServiceUnavailable
            advanceTimeBy(2000); runCurrent()
            val calls = f.headCalls
            assertEquals(original, f.controller.state.value.messages)
            assertFalse(f.controller.state.value.busy)
            assertNull(f.controller.state.value.error)
            assertNotNull(f.controller.state.value.historySyncIssue)
            advanceTimeBy(2000); runCurrent(); assertEquals(calls, f.headCalls)
            advanceTimeBy(2000); runCurrent(); assertEquals(calls + 1, f.headCalls)
            f.status = HttpStatusCode.OK; f.append(); advanceTimeBy(8000); runCurrent()
            assertEquals(4, f.controller.state.value.messages.size)
            assertNull(f.controller.state.value.historySyncIssue)
        } finally { f.controller.close(); Dispatchers.resetMain() }
    }

    @Test fun remoteDeletionAndRealSessionExpiryAreHandledWithoutRestoringDeletedData() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val f = Fixture()
        try {
            runCurrent(); f.show(); runCurrent()
            f.deleted = true; advanceTimeBy(2000); runCurrent()
            assertTrue(f.controller.state.value.messages.isEmpty())
            assertNull(f.controller.state.value.conversationId)
            f.status = HttpStatusCode.Unauthorized; advanceTimeBy(2000); runCurrent()
            assertFalse(f.controller.state.value.authenticated)
            assertNull(f.store.token)
            assertTrue(f.controller.state.value.error!!.contains("세션"))
            val calls = f.headCalls; advanceTimeBy(10000); runCurrent(); assertEquals(calls, f.headCalls)
        } finally { f.controller.close(); Dispatchers.resetMain() }
    }
}
