package com.trotter.mobilev2

import android.content.Context
import android.net.Uri
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The receipt is independent of React/auth startup. Never put bearer tokens in WorkManager data. */
object DreamShareStore {
  private const val KEY_ALIAS = "trotter.dream-share.session.v1"
  private var authRevision = 0
  private var bridgeId: String? = null
  private var credentialBlocked = false
  data class Session(val apiBaseUrl: String, val ownerId: Int, val token: String, val revision: Int)

  @Synchronized fun attachBridge(id: String) {
    // A Metro reload creates a new JS auth revision sequence in the same process.
    bridgeId = id
    authRevision = 0
  }
  @Synchronized fun invalidateForBridge(context: Context, revision: Int, id: String) {
    if (bridgeId == id) invalidate(context, revision)
  }
  @Synchronized fun configureForBridge(context: Context, apiBaseUrl: String, ownerId: Int, token: String, revision: Int, id: String) {
    if (bridgeId == id) configure(context, apiBaseUrl, ownerId, token, revision)
  }

  private fun inbox(context: Context) = AtomicFile(File(context.noBackupFilesDir, "dream-share-inbox.json"))
  private fun tombstone(context: Context) = File(context.noBackupFilesDir, "dream-share-session-blocked")
  private fun Session.owner() = DreamShareInbox.Owner(apiBaseUrl, ownerId)
  private fun credential(context: Context) = AtomicFile(File(context.noBackupFilesDir, "dream-share-session.aes"))
  private fun read(context: Context): MutableList<JSONObject> {
    val file = inbox(context)
    val raw = try { file.openRead().bufferedReader().use { it.readText() } } catch (_: FileNotFoundException) { return mutableListOf() }
    val array = JSONArray(raw)
    return (0 until array.length()).map { array.getJSONObject(it) }.toMutableList()
  }
  private fun write(context: Context, entries: List<JSONObject>) {
    val file = inbox(context)
    val output = file.startWrite()
    try { output.write(JSONArray(entries).toString().toByteArray()); file.finishWrite(output) }
    catch (error: Exception) { file.failWrite(output); throw error }
  }
  private fun key(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
      init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    }.generateKey()
  }

  @Synchronized fun session(context: Context): Session? {
    val file = credential(context)
    if (credentialBlocked || tombstone(context).exists()) return null
    return try {
      val envelope = JSONObject(file.openRead().bufferedReader().use { it.readText() })
      val cipher = Cipher.getInstance("AES/GCM/NoPadding")
      cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(envelope.getString("iv"), Base64.NO_WRAP)))
      val value = JSONObject(String(cipher.doFinal(Base64.decode(envelope.getString("data"), Base64.NO_WRAP))))
      Session(value.getString("apiBaseUrl"), value.getInt("ownerId"), value.getString("token"), authRevision)
    } catch (_: Exception) { file.delete(); null }
  }

  @Synchronized fun invalidate(context: Context, revision: Int) {
    if (revision < authRevision) return
    authRevision = revision
    credentialBlocked = true
    // A failed deletion must not let the background worker reuse this credential after restart.
    runCatching { tombstone(context).writeText("blocked") }
    val file = credential(context)
    file.delete()
    if (file.baseFile.exists() || File(file.baseFile.path + ".bak").exists()) {
      // Even a filesystem failure should leave any old ciphertext unreadable.
      runCatching { KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry(KEY_ALIAS) } }
    }
    check(!file.baseFile.exists() && !File(file.baseFile.path + ".bak").exists()) { "The share sign-in could not be cleared." }
  }

  @Synchronized fun configure(context: Context, apiBaseUrl: String, ownerId: Int, token: String, revision: Int) {
    if (revision != authRevision) return // A stale /auth/me response cannot resurrect a signed-out account.
    val base = apiBaseUrl.trimEnd('/')
    val parsed = Uri.parse(base)
    require(parsed.scheme == "https" || (BuildConfig.DEBUG && parsed.scheme == "http" && parsed.host in listOf("localhost", "127.0.0.1", "10.0.2.2")))
    require(parsed.userInfo == null && parsed.query == null && parsed.fragment == null && ownerId > 0 && token.isNotBlank() && !token.any { it.isWhitespace() })
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
    val content = JSONObject().put("apiBaseUrl", base).put("ownerId", ownerId).put("token", token).toString()
    val envelope = JSONObject().put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
      .put("data", Base64.encodeToString(cipher.doFinal(content.toByteArray()), Base64.NO_WRAP)).toString()
    val file = credential(context)
    val output = file.startWrite()
    try { output.write(envelope.toByteArray()); file.finishWrite(output) }
    catch (error: Exception) { file.failWrite(output); throw error }
    val entries = read(context)
    DreamShareInbox.bind(entries, DreamShareInbox.Owner(base, ownerId))
    write(context, entries)
    val blocked = tombstone(context)
    check(!blocked.exists() || blocked.delete()) { "Background sharing could not be enabled." }
    credentialBlocked = false
  }

  fun canonicalUrl(text: String) = DreamShareInbox.canonicalUrl(text)

  @Synchronized fun capture(context: Context, text: String): JSONObject {
    val entries = read(context)
    val item = DreamShareInbox.capture(entries, session(context)?.owner(), text, System.currentTimeMillis())
    write(context, entries)
    return JSONObject(item.toString())
  }

  @Synchronized fun receipt(context: Context, id: String): JSONObject? = read(context).find { it.optString("id") == id }
  @Synchronized fun visible(context: Context): List<JSONObject> {
    val active = session(context) ?: return emptyList()
    return read(context).filter { DreamShareInbox.belongs(it, active.owner()) }
  }
  @Synchronized fun next(context: Context, active: Session, receiptId: String? = null): JSONObject? {
    val entries = read(context)
    if (DreamShareInbox.recoverExhausted(entries, active.owner())) write(context, entries)
    return DreamShareInbox.next(if (receiptId == null) entries else entries.filter { it.optString("id") == receiptId }, active.owner())
  }
  @Synchronized fun update(context: Context, id: String, generation: Int, changes: JSONObject) {
    val entries = read(context)
    if (DreamShareInbox.update(entries, id, generation, changes)) write(context, entries)
  }
  @Synchronized fun retry(context: Context, id: String) {
    val active = session(context) ?: return
    val entries = read(context)
    DreamShareInbox.retry(entries, active.owner(), id)
    write(context, entries)
  }
  @Synchronized fun acknowledge(context: Context, id: String) {
    val active = session(context) ?: return
    val entries = read(context)
    DreamShareInbox.acknowledge(entries, active.owner(), id)
    write(context, entries)
  }
}
