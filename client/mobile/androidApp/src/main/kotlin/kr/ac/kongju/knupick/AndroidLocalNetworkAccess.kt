package kr.ac.kongju.knupick

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kr.ac.kongju.knupick.data.ApiException
import kr.ac.kongju.knupick.data.isLocalNetworkHost
import java.net.InetAddress

/** Only the Activity presents the system prompt; no Activity or credentials are retained here. */
class AndroidLocalNetworkAccess(private val context: Context) {
    private val mutex = Mutex()
    private val mutableRequest = MutableStateFlow(false)
    val request = mutableRequest.asStateFlow()
    private var result: CompletableDeferred<Boolean>? = null

    suspend fun ensureAccess(host: String) {
        if (Build.VERSION.SDK_INT < 37 || granted()) return
        // Also cover an HTTPS hostname resolving to a private LAN address. DNS failures
        // remain ordinary connection failures; .local is gated before mDNS resolution.
        val local = isLocalNetworkHost(host) || withContext(Dispatchers.IO) {
            runCatching { InetAddress.getAllByName(host).any {
                it.isSiteLocalAddress || it.isLinkLocalAddress || it.isLoopbackAddress ||
                    (it.address.size == 16 && (it.address[0].toInt() and 0xfe) == 0xfc)
            } }.getOrDefault(false)
        }
        if (!local) return
        mutex.withLock {
            if (granted()) return@withLock
            withContext(Dispatchers.Main.immediate) {
                val pending = CompletableDeferred<Boolean>()
                result = pending
                mutableRequest.value = true
                try {
                    if (!pending.await() || !granted()) throw ApiException(403,
                        "로컬 서버에 연결하려면 ‘주변 기기’ 권한을 허용해주세요. 거부했다면 Android 설정 → 앱 → KNU PICK → 권한에서 변경할 수 있습니다.")
                } finally {
                    result = null
                    mutableRequest.value = false
                }
            }
        }
    }

    // Consume before launch so rotating the Activity does not launch a second prompt.
    fun promptLaunched() { mutableRequest.value = false }
    fun permissionResult(allowed: Boolean) { result?.complete(allowed) }
    private fun granted() = Build.VERSION.SDK_INT < 37 ||
        context.checkSelfPermission(Manifest.permission.ACCESS_LOCAL_NETWORK) == PackageManager.PERMISSION_GRANTED
}
