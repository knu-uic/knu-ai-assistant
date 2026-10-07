package kr.ac.kongju.knupick

import android.app.Application
import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModelProvider
import io.ktor.client.HttpClient
import io.ktor.client.engine.okhttp.OkHttp
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.HttpSend
import io.ktor.client.plugins.plugin
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import kr.ac.kongju.knupick.data.KnuApi
import kr.ac.kongju.knupick.ui.KnuApp

class PickViewModel(application: Application) : AndroidViewModel(application) {
    val localNetwork = AndroidLocalNetworkAccess(application)
    private val client = HttpClient(OkHttp) {
        followRedirects = false // Never forward student credentials to a redirected server.
        install(HttpTimeout) { requestTimeoutMillis = 180000; connectTimeoutMillis = 15000; socketTimeoutMillis = 180000 }
    }
    init {
        client.plugin(HttpSend).intercept { request ->
            localNetwork.ensureAccess(request.url.host)
            execute(request)
        }
    }
    val controller = AppController(KnuApi(client, AndroidSessionStore(application)), allowLocalHttp = BuildConfig.DEBUG)
    override fun onCleared() { controller.close() }
}

class MainActivity : ComponentActivity() {
    private val pickViewModel by lazy { ViewModelProvider(this)[PickViewModel::class.java] }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val viewModel = pickViewModel
        setContent {
            val requested by viewModel.localNetwork.request.collectAsState()
            val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission(),
                viewModel.localNetwork::permissionResult)
            LaunchedEffect(requested) {
                if (requested && Build.VERSION.SDK_INT >= 37) {
                    viewModel.localNetwork.promptLaunched()
                    permission.launch(Manifest.permission.ACCESS_LOCAL_NETWORK)
                }
            }
            KnuApp(viewModel.controller, ::openUrl)
        }
    }
    override fun onStart() { super.onStart(); pickViewModel.controller.setForeground(true) }
    override fun onStop() { pickViewModel.controller.setForeground(false); super.onStop() }
    private fun openUrl(value: String) {
        val uri = Uri.parse(value)
        if (uri.scheme !in listOf("https", "http") || uri.host.isNullOrBlank()) {
            Toast.makeText(this, "안전한 웹 주소가 아닙니다.", Toast.LENGTH_SHORT).show()
            return
        }
        try { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
        catch (_: Exception) { Toast.makeText(this, "브라우저를 열 수 없습니다.", Toast.LENGTH_SHORT).show() }
    }
}
