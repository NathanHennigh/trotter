package com.trotter.mobilev2

import org.json.JSONObject
import java.util.UUID

/** Account/generation rules are pure so interrupted uploads can be regression-tested without Android UI. */
object DreamShareInbox {
  data class Owner(val apiBaseUrl: String, val id: Int)
  fun belongs(item: JSONObject, owner: Owner) = item.optInt("ownerId") == owner.id && item.optString("apiBaseUrl") == owner.apiBaseUrl

  fun canonicalUrl(text: String): String? {
    val candidate = Regex("https?://(?:www\\.)?instagram\\.com/(reel|reels|p|tv)/([A-Za-z0-9_-]+)", RegexOption.IGNORE_CASE).find(text) ?: return null
    val kind = candidate.groupValues[1].lowercase().let { if (it == "reels") "reel" else it }
    return "https://www.instagram.com/$kind/${candidate.groupValues[2]}/"
  }

  fun bind(entries: List<JSONObject>, owner: Owner) {
    entries.forEach { item ->
      if (item.isNull("ownerId")) item.put("ownerId", owner.id).put("apiBaseUrl", owner.apiBaseUrl)
      if (belongs(item, owner) && item.optString("status") == "sign_in") item.put("status", "queued").put("attempts", 0).remove("message")
    }
  }

  fun capture(entries: MutableList<JSONObject>, owner: Owner?, text: String, now: Long): JSONObject {
    val url = canonicalUrl(text) ?: throw IllegalArgumentException("Share an Instagram post or reel link to save it to Dreams.")
    entries.removeAll { it.optString("status") == "saved" && now - it.optLong("createdAt") > 7 * 86400000L }
    val existing = entries.firstOrNull { it.optString("sourceUrl") == url && (if (owner == null) it.isNull("ownerId") else belongs(it, owner)) }
    if (existing != null) {
      val captionArrived = text.trim().length > existing.optString("sharedText").length
      if (captionArrived || existing.optString("status") in listOf("failed", "saved")) {
        if (captionArrived) existing.put("sharedText", text.trim().take(60000))
        existing.put("generation", existing.optInt("generation", 1) + 1).put("status", if (owner == null) "sign_in" else "queued").put("attempts", 0)
        existing.remove("itemId"); existing.remove("dreamId"); existing.remove("message")
      }
      return existing
    }
    check(entries.count { it.optString("status") != "saved" } < 100) { "Your saved links are safe. Open Dreams to finish sending them before adding more." }
    val item = JSONObject().put("id", UUID.randomUUID().toString()).put("sourceUrl", url).put("sharedText", text.trim().take(60000))
      .put("createdAt", now).put("generation", 1).put("attempts", 0).put("status", if (owner == null) "sign_in" else "queued")
    if (owner != null) item.put("ownerId", owner.id).put("apiBaseUrl", owner.apiBaseUrl)
    entries.add(item)
    return item
  }

  fun recoverExhausted(entries: List<JSONObject>, owner: Owner): Boolean {
    val exhausted = entries.filter { belongs(it, owner) && it.optString("status") in listOf("queued", "uploading") && it.optInt("attempts") >= 8 }
    exhausted.forEach { it.put("status", "failed").put("message", "Kept on this phone. Open Dreams to retry sending it.") }
    return exhausted.isNotEmpty()
  }
  fun next(entries: List<JSONObject>, owner: Owner) = entries.firstOrNull { belongs(it, owner) &&
    it.optString("status") in listOf("queued", "uploading") && it.optInt("attempts") < 8 }
  fun update(entries: List<JSONObject>, id: String, generation: Int, changes: JSONObject): Boolean {
    val item = entries.find { it.optString("id") == id && it.optInt("generation", 1) == generation } ?: return false
    changes.keys().forEach { item.put(it, changes.get(it)) }
    return true
  }
  fun retry(entries: List<JSONObject>, owner: Owner, id: String) {
    entries.find { it.optString("id") == id && belongs(it, owner) && it.optString("status") != "saved" }?.let {
      it.put("generation", it.optInt("generation", 1) + 1).put("status", "queued").put("attempts", 0).remove("message")
    }
  }
  fun acknowledge(entries: MutableList<JSONObject>, owner: Owner, id: String) {
    entries.removeAll { it.optString("id") == id && it.optString("status") == "saved" && belongs(it, owner) }
  }
}
