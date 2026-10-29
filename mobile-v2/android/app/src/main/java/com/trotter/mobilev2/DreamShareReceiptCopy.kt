package com.trotter.mobilev2

/** User-facing copy follows the durable receipt state, never an optimistic upload. */
data class DreamShareReceiptCopy(val title: String, val detail: String, val action: String) {
  companion object {
    fun forState(status: String, caption: String = ""): DreamShareReceiptCopy = when (status) {
      "saving" -> DreamShareReceiptCopy("Saving…", "Keeping your link.", "")
      "saved" -> DreamShareReceiptCopy("Saved to Dreams", caption.replace(Regex("https?://\\S+"), "").trim(), "Open →")
      "sign_in" -> DreamShareReceiptCopy("Sign in to finish saving", "Your link is kept on this phone.", "Sign in →")
      "failed" -> DreamShareReceiptCopy("Saved on this phone", "Couldn’t send it to Dreams.", "Retry →")
      "storage_failed" -> DreamShareReceiptCopy("Couldn’t save this link", "Please share it again.", "Close")
      else -> DreamShareReceiptCopy("Saved on this phone", "We’ll send it when connected.", "Open →")
    }
  }
}
