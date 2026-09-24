package com.trotter.mobilev2

/** Receipt timing follows durable capture, not uploads or polling. No Android clock is needed in tests. */
class DreamShareReceiptPolicy(snapshot: Snapshot = Snapshot()) {
  data class Snapshot(
    val captured: Boolean = false,
    val storageFailed: Boolean = false,
    val status: String = "",
    val remainingMs: Long = 2200L,
  )

  private var state = snapshot
  private var visible = false
  private var interacting = false
  private var accessible = false
  private var startedAt: Long? = null

  val canDismiss: Boolean get() = state.captured || state.storageFailed
  val captured: Boolean get() = state.captured
  private val eligible: Boolean get() = state.captured && !state.storageFailed &&
    state.status !in setOf("sign_in", "failed") && visible && !interacting && !accessible

  private fun advance(now: Long) {
    startedAt?.let { start -> state = state.copy(remainingMs = (state.remainingMs - (now - start).coerceAtLeast(0)).coerceAtLeast(0)) }
    startedAt = null
  }

  fun stored(status: String, now: Long): Boolean {
    advance(now)
    val firstCapture = !state.captured
    state = state.copy(captured = true, storageFailed = false, status = status)
    resume(now)
    return firstCapture
  }

  fun storageFailed(now: Long) { advance(now); state = state.copy(storageFailed = true) }

  fun visibility(visible: Boolean, now: Long) { advance(now); this.visible = visible; resume(now) }
  fun accessibility(enabled: Boolean, now: Long) { advance(now); accessible = enabled; resume(now) }
  fun interaction(active: Boolean, now: Long) {
    advance(now)
    // Deliberate interaction buys another full reading interval, but a 450 ms network poll does not.
    if (!active && interacting) state = state.copy(remainingMs = 2200L)
    interacting = active
    resume(now)
  }
  private fun resume(now: Long) { if (eligible) startedAt = now }

  fun dismissalDelay(now: Long): Long? {
    advance(now)
    resume(now)
    return state.remainingMs.takeIf { eligible }
  }

  fun snapshot(now: Long): Snapshot { advance(now); resume(now); return state }
}
