package com.trotter.mobilev2

fun main() {
  for (state in listOf("queued", "uploading", "failed")) {
    check(DreamShareReceiptCopy.forState(state).title == "Saved on this phone")
  }
  check(DreamShareReceiptCopy.forState("failed").action == "Retry →")
  check(DreamShareReceiptCopy.forState("sign_in").title == "Sign in to finish saving")
  check(DreamShareReceiptCopy.forState("storage_failed").title == "Couldn’t save this link")
  check(DreamShareReceiptCopy.forState("storage_failed").action == "Close")
  check(DreamShareReceiptCopy.forState("saving").action.isEmpty())
  val saved = DreamShareReceiptCopy.forState("saved", "A weekend in Kyoto https://instagram.com/reel/demo")
  check(saved.title == "Saved to Dreams" && saved.detail == "A weekend in Kyoto")
  check(DreamShareReceiptCopy.forState("saved", "https://instagram.com/reel/demo").detail.isEmpty())
  println("PASS receipt copy distinguishes durable local capture, upload, auth and storage failure")
}
