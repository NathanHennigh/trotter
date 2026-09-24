package com.trotter.mobilev2

/** Executes the exact production timing gate with a deterministic monotonic clock. */
fun main() {
  var passed = 0
  fun test(name: String, run: () -> Unit) { run(); passed++; println("PASS $name") }
  test("back, swipe, outside tap and the deadline cannot dismiss before durable capture") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0)
    check(!policy.canDismiss && !policy.captured && policy.dismissalDelay(20_000) == null)
    check(policy.stored("queued", 20_000))
    check(policy.canDismiss && policy.captured)
    check(policy.dismissalDelay(20_000) == 2200L)
  }
  test("network polling never renews the two-second receipt") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0)
    policy.stored("queued", 0)
    for (time in 450L..1800L step 450) {
      check(!policy.stored("uploading", time))
      check(policy.dismissalDelay(time) == 2200L - time)
    }
    policy.stored("saved", 2000)
    check(policy.dismissalDelay(2200) == 0L)
  }
  test("offline capture is safe to dismiss without waiting for a server or announcing a destination") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0)
    policy.stored("queued", 10)
    check(policy.canDismiss && policy.dismissalDelay(2210) == 0L)
  }
  test("holding or scrolling the receipt pauses dismissal and leaves time after release") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0); policy.stored("saved", 0)
    policy.interaction(true, 1900)
    check(policy.dismissalDelay(10_000) == null)
    policy.interaction(false, 10_001)
    check(policy.dismissalDelay(10_001) == 2200L)
    check(policy.dismissalDelay(12_201) == 0L)
  }
  test("a screen reader keeps the receipt open until explicitly dismissed") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0); policy.accessibility(true, 0); policy.stored("saved", 0)
    check(policy.canDismiss && policy.dismissalDelay(100_000) == null)
    policy.accessibility(false, 100_001)
    check(policy.dismissalDelay(100_001) == 2200L)
  }
  test("auth and transmission failures remain actionable rather than disappearing") {
    for (status in listOf("sign_in", "failed")) {
      val policy = DreamShareReceiptPolicy()
      policy.visibility(true, 0); policy.stored(status, 0)
      check(policy.canDismiss && policy.dismissalDelay(100_000) == null)
      policy.stored("queued", 100_001)
      check(policy.dismissalDelay(100_001) == 2200L)
    }
  }
  test("disk failure permits dismissal but never claims a durable saved reel") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0); policy.storageFailed(1)
    check(policy.canDismiss && !policy.captured && policy.dismissalDelay(100_000) == null)
  }
  test("background and focus loss preserve the user's remaining reading time") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0); policy.stored("saved", 0)
    policy.visibility(false, 1000)
    check(policy.dismissalDelay(60_000) == null)
    policy.visibility(true, 60_001)
    check(policy.dismissalDelay(60_001) == 1200L)
  }
  test("rotation retains the capture gate and countdown without confirming twice") {
    val original = DreamShareReceiptPolicy()
    original.visibility(true, 0); original.stored("uploading", 0)
    val rotated = DreamShareReceiptPolicy(original.snapshot(900))
    check(rotated.canDismiss && rotated.captured && rotated.dismissalDelay(2000) == null)
    rotated.visibility(true, 2001)
    check(!rotated.stored("saved", 2001))
    check(rotated.dismissalDelay(2001) == 1300L)
  }
  test("repeated lifecycle callbacks do not double-charge elapsed time") {
    val policy = DreamShareReceiptPolicy()
    policy.visibility(true, 0); policy.stored("saved", 0)
    repeat(8) { check(policy.dismissalDelay(1000) == 1200L) }
    policy.visibility(true, 1000)
    check(policy.dismissalDelay(1200) == 1000L)
  }
  println("$passed production receipt lifecycle checks passed.")
}
