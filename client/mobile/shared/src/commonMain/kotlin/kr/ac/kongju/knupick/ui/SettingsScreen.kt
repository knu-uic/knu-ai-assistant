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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kr.ac.kongju.knupick.AppController
import kr.ac.kongju.knupick.AppState
import kr.ac.kongju.knupick.data.LlmAccount

@Composable internal fun SettingsScreen(state: AppState, controller: AppController, serverSettings: () -> Unit, openUrl: (String) -> Unit) {
    var interests by remember(state.profile?.interests) { mutableStateOf(state.profile?.interests.orEmpty()) }
    var provider by remember { mutableStateOf("openai") }
    var apiKey by remember { mutableStateOf("") }
    var removing by remember { mutableStateOf<LlmAccount?>(null) }
    var loggingOut by remember { mutableStateOf(false) }
    removing?.let { account -> AlertDialog(onDismissRequest = { removing = null }, title = { Text("개인 모델 연결 해제") },
        text = { Text("${account.label} 연결을 서버에서 삭제할까요? 다시 사용하려면 재연결해야 합니다.") },
        confirmButton = { TextButton(onClick = { controller.removeAccount(account); removing = null }) { Text("연결 해제") } },
        dismissButton = { TextButton(onClick = { removing = null }) { Text("취소") } }) }
    if (loggingOut) AlertDialog(onDismissRequest = { loggingOut = false }, title = { Text("로그아웃") },
        text = { Text("이 기기에서 로그아웃할까요? 서버에 저장된 대화 기록은 유지됩니다.") },
        confirmButton = { TextButton(onClick = { controller.logout(); loggingOut = false }) { Text("로그아웃") } },
        dismissButton = { TextButton(onClick = { loggingOut = false }) { Text("취소") } })
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item { PageTitle("내 정보", "내 계정, 관심사와 대화 모델을 관리하세요.") }
        item { PickCard {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                BrandMark(50)
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(state.profile?.name ?: "학생", fontSize = 21.sp, fontWeight = FontWeight.Bold)
                    Caption(listOfNotNull(state.profile?.major, state.profile?.year?.let { "${it}학년" }, state.profile?.student_id).joinToString(" · "))
                }
            }
            Tag(if (state.profile?.portal_linked == true) "포털 연동됨" else "포털 자료 확인 중")
            Caption(if (state.profile?.lms_linked == true) "LMS 연동됨" else "LMS 자료 없음 · 학사에서 동기화할 수 있습니다.")
        } }
        item { PickCard {
            Text("관심 키워드", fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Caption("최대 6개까지 선택할 수 있습니다.")
            listOf(listOf("인턴", "장학금", "캡스톤"), listOf("해커톤", "교환학생", "공모전"), listOf("근로장학", "특강", "동아리"), listOf("취업박람회")).forEach { group ->
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    group.forEach { keyword -> FilterChip(keyword in interests, {
                        interests = if (keyword in interests) interests - keyword else if (interests.size < 6) interests + keyword else interests
                    }, label = { Text(keyword, fontSize = 12.sp) }, enabled = !state.busy) }
                }
            }
            Button(onClick = { controller.saveInterests(interests) }, enabled = !state.busy && interests != state.profile?.interests) { Text("관심사 저장") }
        } }
        item { Text("대화용 개인 AI 계정", fontSize = 19.sp, fontWeight = FontWeight.Bold) }
        item { Caption("본인의 대화에만 사용됩니다. 학교 공통 모델과 별개이며, 개인 계정의 사용 한도 또는 API 비용이 적용될 수 있습니다.") }
        if (state.accounts.isEmpty()) item { PickCard { Caption("연결된 개인 계정이 없습니다. 아래에서 계정을 연결해주세요.") } }
        items(state.accounts, key = { it.id }) { account -> PickCard {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(account.label, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                if (account.active) Tag("사용 중")
            }
            Caption("${account.provider} · ${account.model.ifEmpty { "모델 선택 필요" }}")
            TextButton(onClick = { controller.loadModels(account) }, enabled = !state.busy) { Text("사용 가능한 모델 불러오기") }
            state.models[account.id]?.let { models ->
                if (models.isEmpty()) Caption("사용 가능한 모델이 없습니다.")
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    models.forEach { model -> OutlinedButton(onClick = { controller.selectModel(account, model) }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text(model, fontSize = 12.sp) } }
                }
            }
            TextButton(onClick = { removing = account }, enabled = !state.busy) { Text("연결 해제", color = MaterialTheme.colorScheme.error) }
        } }
        item { PickCard {
            Text("Codex 계정 연결", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Caption("외부 브라우저에서 본인 계정을 인증합니다. 인증 토큰은 KNU 서버가 관리하며 앱에는 전달하지 않습니다.")
            val login = state.codexLogin
            if (login == null) {
                OutlinedButton(onClick = controller::startCodex, enabled = !state.busy && !state.demo) { Text("Codex 인증 시작") }
            } else {
                Text(login.user_code, color = Blue, fontWeight = FontWeight.Bold, fontSize = 24.sp)
                Button(onClick = { openUrl(login.verification_url) }) { Text("브라우저에서 인증하기") }
                Caption("인증 완료를 기다리고 있습니다. 앱으로 돌아오면 연결 상태가 갱신됩니다.")
                TextButton(onClick = controller::cancelCodex) { Text("인증 대기 취소") }
            }
        } }
        item { PickCard {
            Text("API 키 연결", fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(provider == "openai", { provider = "openai"; apiKey = "" }, label = { Text("OpenAI") }, enabled = !state.busy)
                FilterChip(provider == "google", { provider = "google"; apiKey = "" }, label = { Text("Gemini") }, enabled = !state.busy)
            }
            OutlinedTextField(apiKey, { apiKey = it }, modifier = Modifier.fillMaxWidth(), label = { Text("개인 API 키") },
                visualTransformation = PasswordVisualTransformation(), singleLine = true, enabled = !state.busy && !state.demo)
            Button(onClick = { controller.addKey(provider, apiKey); apiKey = "" }, enabled = !state.busy && !state.demo && apiKey.trim().length in 20..500) { Text("서버에 계정 연결") }
            Caption("키는 기기에 저장하지 않습니다. 연결한 뒤 사용할 모델을 선택해주세요.")
        } }
        item { PickCard {
            Text("서버 연결", fontWeight = FontWeight.Bold)
            Caption(controller.serverUrl)
            TextButton(onClick = serverSettings, enabled = !state.busy) { Text("서버 주소 변경") }
            Caption("KMP · Compose Multiplatform\nAndroid 우선 개발 · 0.1.0")
        } }
        item { OutlinedButton(onClick = { loggingOut = true }, modifier = Modifier.fillMaxWidth()) { Text(if (state.demo) "데모 나가기" else "로그아웃") } }
    }
}
