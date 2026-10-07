package kr.ac.kongju.knupick

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kr.ac.kongju.knupick.data.SessionStore
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Only the KNU JWT is persisted, encrypted by a non-exportable Android Keystore key. */
class AndroidSessionStore(context: Context) : SessionStore {
    private val prefs = context.getSharedPreferences("knu_pick_session", Context.MODE_PRIVATE)
    private val alias = "knu_pick_session_v1"
    override var serverUrl: String
        get() = prefs.getString("server", null) ?: if (BuildConfig.DEBUG) "http://10.0.2.2:8000" else ""
        set(value) { prefs.edit().putString("server", value).apply() }
    private fun key(): SecretKey {
        val keystore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keystore.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    override var token: String?
        get() {
            val value = prefs.getString("token", null) ?: return null
            return try {
                val parts = value.split('.')
                require(parts.size == 2)
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
                String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), Charsets.UTF_8)
            } catch (_: Exception) { prefs.edit().remove("token").apply(); null }
        }
        set(value) {
            if (value == null) { prefs.edit().remove("token").apply(); return }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            prefs.edit().putString("token", Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + "." + Base64.encodeToString(encrypted, Base64.NO_WRAP)).apply()
        }
}
