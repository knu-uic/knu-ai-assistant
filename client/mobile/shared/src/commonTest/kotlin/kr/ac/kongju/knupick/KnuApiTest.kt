package kr.ac.kongju.knupick

import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.*
import io.ktor.http.*
import io.ktor.http.content.TextContent
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.coroutines.flow.first
import kotlinx.serialization.json.*
import kr.ac.kongju.knupick.data.*
import kotlin.test.*

class KnuApiTest {
    @Test fun localNetworkPermissionClassificationIsSeparateFromCleartextPolicy() {
        for (host in listOf("10.0.2.2", "192.168.0.10", "172.16.1.1", "169.254.1.2", "localhost", "KNU.local.", "[::1]", "fd00::1", "fe80::1")) {
            assertTrue(isLocalNetworkHost(host), host)
        }
        for (host in listOf("knu.example.com", "8.8.8.8", "172.15.1.1", "172.32.1.1", "10.0.2.999", "2001:4860:4860::8888")) {
            assertFalse(isLocalNetworkHost(host), host)
        }
        assertFailsWith<IllegalArgumentException> { normalizeServerUrl("http://knu.local", true) }
    }

    @Test fun healthDoesNotSendStudentCredentialsOrBearer() = runTest {
        val client = HttpClient(MockEngine { request ->
            assertEquals("/api/health", request.url.encodedPath)
            assertEquals(HttpMethod.Get, request.method)
            assertNull(request.headers[HttpHeaders.Authorization])
            respond("""{"status":"ok","min_app_version":"1.0.0"}""", headers = headersOf(HttpHeaders.ContentType, "application/json"))
        })
        try { KnuApi(client, MemorySessionStore().apply { token = "must-not-be-sent" }).health() }
        finally { client.close() }
    }

    @Test fun urlsRequireHttpsExceptDebugPrivateAddresses() {
        assertEquals("https://knu.example.com", normalizeServerUrl("https://knu.example.com/api/", false))
        assertEquals("http://10.0.2.2:8000", normalizeServerUrl("http://10.0.2.2:8000", true))
        assertEquals("http://192.168.0.10:8000", normalizeServerUrl("http://192.168.0.10:8000", true))
        for (url in listOf("http://knu.example.com", "http://8.8.8.8", "https://user:password@example.com", "https://example.com/private", "https://example.com?token=secret", "file:///tmp/test")) {
            assertFailsWith<IllegalArgumentException> { normalizeServerUrl(url, true) }
        }
        assertFailsWith<IllegalArgumentException> { normalizeServerUrl("http://10.0.2.2:8000", false) }
    }

    @Test fun chatSendsOnlyServerIdentityRevisionAndQuestionNotFixedCountHistory() = runTest {
        val store=MemorySessionStore("https://knu.example.com").apply { token="student-token" }
        val client=HttpClient(MockEngine { request ->
            assertEquals("Bearer student-token", request.headers[HttpHeaders.Authorization])
            val body=Json.parseToJsonElement((request.body as TextContent).text).jsonObject
            assertFalse("history" in body)
            assertEquals("conversation-id",body["conversation_id"]?.jsonPrimitive?.content)
            assertEquals(42,body["revision"]?.jsonPrimitive?.int)
            assertEquals("school",body["source"]?.jsonPrimitive?.content)
            respond("""{"answer":"앞의 맥락을 참고한 답변","unknown":"ignored"}""",headers=headersOf(HttpHeaders.ContentType,"application/json"))
        })
        val api=KnuApi(client,store)
        assertEquals("앞의 맥락을 참고한 답변",api.chat("앞에서 한 말 계속", "conversation-id",42,"request-id","school").answer)
        client.close()
    }

    @Test fun loginDoesNotSendOldServersBearerAndTaskDoneHandles204() = runTest {
        val store=MemorySessionStore("https://knu.example.com").apply { token="old-token" }
        val client=HttpClient(MockEngine { request ->
            if(request.url.encodedPath.endsWith("portal-login")) {
                assertNull(request.headers[HttpHeaders.Authorization])
                respond("""{"access_token":"new-token"}""",headers=headersOf(HttpHeaders.ContentType,"application/json"))
            } else respond("",HttpStatusCode.NoContent)
        })
        val api=KnuApi(client,store)
        assertEquals("new-token",api.login("20260001","test-only"))
        api.taskDone(1,true)
        client.close()
    }

    @Test fun revisionConflictIsNotReportedAsSuccessfulDelete() = runTest {
        val client=HttpClient(MockEngine { request ->
            assertEquals("7",request.url.parameters["revision"])
            respond("""{"detail":"다른 기기에서 변경"}""",HttpStatusCode.Conflict)
        })
        val error=assertFailsWith<ApiException> { KnuApi(client,MemorySessionStore()).deleteConversation("id",7) }
        assertEquals(409,error.status)
        client.close()
    }

    @Test fun lmsDeletionHandles204WithoutParsingJson() = runTest {
        val client=HttpClient(MockEngine { request ->
            assertEquals(HttpMethod.Delete, request.method)
            assertEquals("/api/me/lms/tasks/12",request.url.encodedPath)
            assertEquals("Bearer test",request.headers[HttpHeaders.Authorization])
            respond("",HttpStatusCode.NoContent)
        })
        try { KnuApi(client,MemorySessionStore().apply { token="test" }).deleteTask(12) }
        finally { client.close() }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun serverTranscriptRefreshAndLostReplyRecoveryPreserveOriginals() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val json=Json { encodeDefaults=true }
        var saved=Conversation("conversation-id","서버 대화","personal",7,"2026-10-07","2026-10-07",
            List(20) { ChatMessage(if(it%2==0) "user" else "assistant","원본 $it") })
        val client=HttpClient(MockEngine { request ->
            val path=request.url.encodedPath
            val text=when(path) {
                "/api/me/conversations/conversation-id" -> json.encodeToString(saved)
                "/api/me/conversations" -> json.encodeToString(ConversationPage(listOf(saved.summary())))
                "/api/chat" -> {
                    val body=Json.parseToJsonElement((request.body as TextContent).text).jsonObject
                    assertFalse("history" in body)
                    assertEquals(8,body["revision"]!!.jsonPrimitive.int)
                    assertEquals("이어서",body["question"]!!.jsonPrimitive.content)
                    saved=saved.copy(revision=9,messages=saved.messages + listOf(ChatMessage("user","이어서"),ChatMessage("assistant","저장된 답변")))
                    return@MockEngine respond("""{"detail":"connection lost after commit"}""",HttpStatusCode.ServiceUnavailable)
                }
                else -> "{}"
            }
            respond(text,headers=headersOf(HttpHeaders.ContentType,"application/json"))
        })
        val controller=AppController(KnuApi(client,MemorySessionStore().apply { token="test" }),true)
        try {
            controller.state.first { !it.busy }
            controller.openConversation(saved.summary()); controller.state.first { !it.busy }
            assertEquals(20,controller.state.value.messages.size)
            saved=saved.copy(revision=8,messages=saved.messages + listOf(ChatMessage("user","다른 기기"),ChatMessage("assistant","변경된 기록")))
            controller.loadHistory(); controller.state.first { !it.busy }
            assertEquals(8,controller.state.value.conversationRevision)
            assertEquals("변경된 기록",controller.state.value.messages.last().content)
            controller.ask("이어서"); controller.state.first { !it.busy }
            assertEquals(24,controller.state.value.messages.size)
            assertEquals("원본 0",controller.state.value.messages.first().content)
            assertEquals(9,controller.state.value.conversationRevision)
            assertNull(controller.state.value.error)
            assertTrue(controller.state.value.message!!.contains("복원"))
            assertFalse(controller.state.value.unsavedHistory)
        } finally { controller.close(); Dispatchers.resetMain() }
    }

    @Test fun academicParsersPreserveDaysRoomsAndNestedCredits() {
        val lessons=parseTimetable(Json.parseToJsonElement("""[{"rows":[["교시","월요일","화요일"],["1교시 주간: (09:00~09:50)","확률통계(03 김영부) 9공710",""]]}]"""))
        assertEquals(1,lessons.size)
        assertEquals("월",lessons.single().day)
        assertEquals("9공710",lessons.single().room)
        assertEquals("09:00~09:50",lessons.single().time)
        assertTrue(parseTimetable(null).isEmpty())
        val credits=parseCredits(Json.parseToJsonElement("""{"졸업":{"전공":{"기준":60,"취득":50}}}""").jsonObject)
        assertEquals("졸업 · 전공",credits.single().label)
        assertEquals("10",credits.single().deficit)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test fun demoNeverCallsSchoolOrModelsAndLogoutClearsState() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val store=MemorySessionStore()
        val client=HttpClient(MockEngine { error("Demo must never make a request") })
        val controller=AppController(KnuApi(client,store),true)
        try {
            controller.demo()
            assertTrue(controller.state.value.authenticated && controller.state.value.demo)
            controller.ask("테스트")
            advanceUntilIdle()
            assertEquals(2,controller.state.value.messages.size)
            assertFalse(controller.state.value.unsavedHistory)
            controller.logout()
            assertFalse(controller.state.value.authenticated)
            assertTrue(controller.state.value.messages.isEmpty())
            assertNull(store.token)
        } finally { controller.close(); Dispatchers.resetMain() }
    }
}
