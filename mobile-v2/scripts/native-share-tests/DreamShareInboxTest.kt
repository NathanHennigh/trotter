package com.trotter.mobilev2

import org.json.JSONObject

/** Runs the production inbox transition rules, not a JavaScript translation of them. */
fun main() {
  var passed = 0
  fun test(name: String, action: () -> Unit) { action(); passed++; println("PASS $name") }
  val alice = DreamShareInbox.Owner("https://api.example.test", 11)
  val bob = DreamShareInbox.Owner("https://api.example.test", 22)
  val stagingAlice = DreamShareInbox.Owner("https://staging.example.test", 11)
  val url = "https://www.instagram.com/reel/example_1/"
  val now = 2_000_000_000L

  test("tracking URLs normalize without accepting lookalike Instagram domains") {
    check(DreamShareInbox.canonicalUrl("Visit https://instagram.com/reels/abc_123/?igsh=tracking today") == "https://www.instagram.com/reel/abc_123/")
    check(DreamShareInbox.canonicalUrl("https://instagram.com.evil.test/reel/abc/") == null)
    check(DreamShareInbox.canonicalUrl("https://example.test/reel/abc/") == null)
  }
  test("signed-out receipt binds once and never crosses a later account") {
    val entries = mutableListOf<JSONObject>()
    val item = DreamShareInbox.capture(entries, null, url, now)
    check(item.optString("status") == "sign_in" && item.isNull("ownerId"))
    DreamShareInbox.bind(entries, alice)
    check(DreamShareInbox.belongs(item, alice) && item.optString("status") == "queued")
    DreamShareInbox.bind(entries, bob)
    check(DreamShareInbox.belongs(item, alice) && !DreamShareInbox.belongs(item, bob))
  }
  test("same URL is independent across verified accounts and API origins") {
    val entries = mutableListOf<JSONObject>()
    listOf(alice, bob, stagingAlice).forEach { DreamShareInbox.capture(entries, it, url, now) }
    check(entries.size == 3 && entries.map { it.getString("id") }.distinct().size == 3)
    check(DreamShareInbox.next(entries, bob)?.getInt("ownerId") == bob.id)
    check(DreamShareInbox.next(entries, stagingAlice)?.getString("apiBaseUrl") == stagingAlice.apiBaseUrl)
  }
  test("later caption invalidates the response from the original upload") {
    val entries = mutableListOf<JSONObject>()
    val item = DreamShareInbox.capture(entries, alice, url, now)
    val id = item.getString("id")
    val oldGeneration = item.getInt("generation")
    item.put("status", "uploading")
    DreamShareInbox.capture(entries, alice, "El Fenn, Marrakech. $url", now + 1)
    check(entries.size == 1 && item.getString("sharedText").contains("El Fenn"))
    check(!DreamShareInbox.update(entries, id, oldGeneration, JSONObject().put("status", "saved").put("itemId", 40)))
    check(item.getString("status") == "queued" && item.isNull("itemId"))
    check(DreamShareInbox.update(entries, id, item.getInt("generation"), JSONObject().put("status", "saved").put("itemId", 40)))
  }
  test("retry after exhaustion resets attempts and rejects a late previous response") {
    val entries = mutableListOf<JSONObject>()
    val item = DreamShareInbox.capture(entries, alice, url, now).put("attempts", 8).put("status", "failed")
    val oldGeneration = item.getInt("generation")
    DreamShareInbox.retry(entries, alice, item.getString("id"))
    check(item.getInt("attempts") == 0 && item.getString("status") == "queued")
    check(!DreamShareInbox.update(entries, item.getString("id"), oldGeneration, JSONObject().put("status", "failed")))
  }
  test("process death on the last upload attempt cannot leave a permanent spinner") {
    val entries = mutableListOf<JSONObject>()
    val exhausted = DreamShareInbox.capture(entries, alice, url, now).put("attempts", 8).put("status", "uploading")
    val next = DreamShareInbox.capture(entries, alice, "https://instagram.com/p/next/", now)
    check(DreamShareInbox.recoverExhausted(entries, alice))
    check(exhausted.getString("status") == "failed")
    check(DreamShareInbox.next(entries, alice) === next)
  }
  test("acknowledgement never discards an unsent receipt or another account's saved receipt") {
    val entries = mutableListOf<JSONObject>()
    val pending = DreamShareInbox.capture(entries, alice, url, now)
    val other = DreamShareInbox.capture(entries, bob, url, now).put("status", "saved")
    DreamShareInbox.acknowledge(entries, alice, pending.getString("id"))
    DreamShareInbox.acknowledge(entries, alice, other.getString("id"))
    check(entries.size == 2)
    pending.put("status", "saved")
    DreamShareInbox.acknowledge(entries, alice, pending.getString("id"))
    check(entries.size == 1 && entries[0] === other)
  }
  test("a deliberate re-share checks the server again after the user may have deleted the old save") {
    val entries = mutableListOf<JSONObject>()
    val old = DreamShareInbox.capture(entries, alice, url, now).put("status", "saved").put("itemId", 50).put("dreamId", 4)
    val again = DreamShareInbox.capture(entries, alice, url, now + 100)
    check(again === old && again.getString("status") == "queued")
    check(again.isNull("itemId") && again.isNull("dreamId") && again.getInt("generation") == 2)
  }
  test("old saved receipts expire but old offline links do not") {
    val entries = mutableListOf<JSONObject>()
    val offline = DreamShareInbox.capture(entries, alice, url, 1)
    DreamShareInbox.capture(entries, alice, "https://instagram.com/p/saved/", 1).put("status", "saved")
    DreamShareInbox.capture(entries, alice, "https://instagram.com/p/new/", now)
    check(entries.size == 2 && entries.any { it === offline })
  }
  test("full inbox refuses new captures without losing earlier links or blocking their duplicate") {
    val entries = mutableListOf<JSONObject>()
    repeat(100) { DreamShareInbox.capture(entries, alice, "https://instagram.com/p/item$it/", now) }
    check(runCatching { DreamShareInbox.capture(entries, alice, url, now) }.isFailure)
    check(entries.size == 100)
    DreamShareInbox.capture(entries, alice, "https://instagram.com/p/item1/", now)
    check(entries.size == 100)
  }
  println("$passed production native inbox state checks passed.")
}
