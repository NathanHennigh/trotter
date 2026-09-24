package com.trotter.mobilev2

import android.content.Context
import android.os.Build
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit

/** Only captures the link. Instagram/AI/Places work stays in the server's durable queue. */
class DreamShareWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
  override fun doWork(): Result {
    repeat(100) {
      if (isStopped) return Result.retry()
      val session = DreamShareStore.session(applicationContext) ?: return Result.success()
      val item = DreamShareStore.next(applicationContext, session, inputData.getString("receiptId")) ?: return Result.success()
      val id = item.getString("id")
      val generation = item.optInt("generation", 1)
      val attempt = item.optInt("attempts") + 1
      DreamShareStore.update(applicationContext, id, generation, JSONObject().put("status", "uploading").put("attempts", attempt))
      val connection = URL("${session.apiBaseUrl}/dreams/share").openConnection() as HttpURLConnection
      try {
        // No redirect may receive the account's bearer credential.
        connection.instanceFollowRedirects = false
        connection.requestMethod = "POST"
        connection.connectTimeout = 12000
        connection.readTimeout = 18000
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Authorization", "Bearer ${session.token}")
        connection.outputStream.use { stream -> stream.write(JSONObject().put("source_url", item.getString("sourceUrl"))
          .put("shared_text", item.optString("sharedText")).toString().toByteArray()) }
        val status = connection.responseCode
        if (isStopped) return Result.success()
        val active = DreamShareStore.session(applicationContext)
        if (active != session) return Result.success() // Never transfer a late receipt to another account.
        when {
          status in 200..299 -> {
            val result = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            val itemId = result.optInt("dream_item_id")
            check(itemId > 0) { "The server did not return a saved post." }
            DreamShareStore.update(applicationContext, id, generation, JSONObject().put("status", "saved")
              .put("itemId", itemId).put("dreamId", result.opt("dream_id") ?: JSONObject.NULL)
              .put("message", "Saved to Dreams. Places are being organized in the background."))
          }
          status == 401 || status == 403 -> {
            DreamShareStore.invalidate(applicationContext, session.revision)
            DreamShareStore.update(applicationContext, id, generation, JSONObject().put("status", "sign_in")
              .put("message", "Your link is kept on this phone. Sign in to send it to Dreams."))
            return Result.success()
          }
          status == 408 || status == 425 || status == 429 || status >= 500 -> throw IllegalStateException("Upload will retry.")
          else -> DreamShareStore.update(applicationContext, id, generation, JSONObject().put("status", "failed")
            .put("message", "Your link is kept on this phone. Open Dreams to try sending it again."))
        }
      } catch (_: Exception) {
        if (DreamShareStore.session(applicationContext) != session) return Result.success()
        DreamShareStore.update(applicationContext, id, generation, JSONObject().put("status", if (attempt < 8) "queued" else "failed")
          .put("message", if (attempt < 8) "Kept on this phone. It will send when a connection is available." else "Kept on this phone. Open Dreams to retry sending it."))
        if (attempt < 8) return Result.retry()
      } finally { connection.disconnect() }
    }
    return Result.retry()
  }

  companion object {
    fun enqueue(context: Context, receiptId: String? = null, restart: Boolean = false) {
      if (receiptId == null) {
        DreamShareStore.visible(context).filter { it.optString("status") in listOf("queued", "uploading") }.forEach {
          enqueue(context, it.getString("id"))
        }
        return
      }
      val builder = OneTimeWorkRequest.Builder(DreamShareWorker::class.java)
        .setInputData(Data.Builder().putString("receiptId", receiptId).build())
        .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        .addTag("trotter-dream-share")
      // Pre-Android 12 expedited WorkManager jobs require a foreground notification.
      // A normal short network job there avoids surprising notification chrome.
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
      // A disconnected/slow upload must not hold every later Instagram share behind its backoff.
      WorkManager.getInstance(context).enqueueUniqueWork("trotter-dream-share-$receiptId",
        if (restart) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.APPEND_OR_REPLACE, builder.build())
    }
  }
}
