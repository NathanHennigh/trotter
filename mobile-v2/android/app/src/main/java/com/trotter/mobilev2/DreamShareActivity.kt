package com.trotter.mobilev2

import android.animation.ValueAnimator
import android.app.Activity
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.view.accessibility.AccessibilityManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.animation.PathInterpolator
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.Future
import kotlin.math.abs

/** A native receipt captures first, then returns to Instagram without starting React or waiting for AI. */
class DreamShareActivity : Activity() {
  private val handler = Handler(Looper.getMainLooper())
  private val io = Executors.newSingleThreadExecutor()
  private var captureRequest: Future<JSONObject>? = null
  private var receiptId: String? = null
  private var receipt: JSONObject? = null
  private var policy = DreamShareReceiptPolicy()
  private var stopped = true
  private var closing = false
  private var pollInFlight = false
  private var confirmed = false
  private var fingerDownY = 0f
  private var fingerDownX = 0f
  private var dragging = false
  private lateinit var shell: LinearLayout
  private lateinit var title: TextView
  private lateinit var detail: TextView
  private lateinit var preview: TextView
  private lateinit var thumbnail: ImageView
  private lateinit var checkmark: TextView
  private lateinit var open: TextView
  private lateinit var close: TextView
  private lateinit var accessibility: AccessibilityManager
  private val ink = Color.parseColor("#31576B")
  private val muted = Color.parseColor("#647680")
  private val paper = Color.parseColor("#FAF8F2")
  private val easeOut = PathInterpolator(0.23f, 1f, 0.32f, 1f)
  private val pollTask = Runnable { poll() }
  private val dismissTask = Runnable {
    if (policy.dismissalDelay(now()) == 0L) dismissReceipt() else scheduleDismissal()
  }
  private val accessibilityListener = AccessibilityManager.TouchExplorationStateChangeListener { enabled ->
    policy.accessibility(enabled, now()); scheduleDismissal()
  }

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    accessibility = getSystemService(ACCESSIBILITY_SERVICE) as AccessibilityManager
    accessibility.addTouchExplorationStateChangeListener(accessibilityListener)
    policy = DreamShareReceiptPolicy(DreamShareReceiptPolicy.Snapshot(
      captured = savedInstanceState?.getBoolean("captured") ?: false,
      storageFailed = savedInstanceState?.getBoolean("storageFailed") ?: false,
      status = savedInstanceState?.getString("status") ?: "",
      remainingMs = savedInstanceState?.getLong("remainingMs", 2200L) ?: 2200L,
    ))
    confirmed = savedInstanceState?.getBoolean("confirmed") ?: false
    policy.accessibility(accessibility.isTouchExplorationEnabled, now())
    window.setGravity(Gravity.BOTTOM)
    window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
    window.attributes = window.attributes.apply { dimAmount = 0.14f; windowAnimations = 0 }
    setFinishOnTouchOutside(false)
    buildReceipt()
    receiptId = savedInstanceState?.getString("receiptId")
    val text = sharedText(intent)
    val persisted = receiptId
    val context = applicationContext
    @Suppress("UNCHECKED_CAST", "DEPRECATION")
    val retained = lastNonConfigurationInstance as? Future<JSONObject>
    // A rotation observes the same capture; it cannot re-share a just-uploaded link or restart its worker.
    captureRequest = retained ?: io.submit<JSONObject> {
      val captured = persisted?.let { DreamShareStore.receipt(context, it) } ?: DreamShareStore.capture(context, text)
      runCatching { DreamShareWorker.enqueue(context, captured.getString("id"), restart = persisted == null) }
      captured
    }
    io.execute {
      try {
        val captured = captureRequest!!.get()
        runOnUiThread {
          if (!isFinishing && !isDestroyed) {
            receiptId = captured.getString("id")
            render(captured)
            poll()
          }
        }
      } catch (error: Exception) {
        runOnUiThread {
          if (!isFinishing && !isDestroyed) {
            policy.storageFailed(now())
            title.text = "Couldn’t save this reel"
            detail.text = (error.cause ?: error).message ?: "Please try sharing it again."
            preview.text = "Your other saves are safe."
            close.isEnabled = true
            open.visibility = View.GONE
            scheduleDismissal()
          }
        }
      }
    }
    loadProvidedThumbnail(intent)
    if (savedInstanceState == null && motionEnabled()) {
      shell.alpha = 0f
      shell.translationY = dp(16).toFloat()
      shell.animate().alpha(1f).translationY(0f).setDuration(180).setInterpolator(easeOut).start()
    }
  }

  private fun now() = SystemClock.elapsedRealtime()
  private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
  private fun motionEnabled() = Build.VERSION.SDK_INT < Build.VERSION_CODES.O || ValueAnimator.areAnimatorsEnabled()
  private fun shape(color: Int, radius: Int, border: Int? = null) = GradientDrawable().apply {
    setColor(color); cornerRadius = dp(radius).toFloat(); border?.let { setStroke(dp(1), it) }
  }
  private fun text(value: String, size: Float, color: Int = ink, serif: Boolean = false) = TextView(this).apply {
    text = value; textSize = size; setTextColor(color)
    typeface = runCatching { Typeface.createFromAsset(assets, if (serif) "share-fonts/Newsreader-Regular.ttf" else "share-fonts/DMSans-Regular.ttf") }
      .getOrElse { Typeface.create(if (serif) "serif" else "sans-serif", Typeface.NORMAL) }
    includeFontPadding = false
  }
  private fun buttonRole(view: TextView) {
    view.accessibilityDelegate = object : View.AccessibilityDelegate() {
      override fun onInitializeAccessibilityNodeInfo(host: View, info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(host, info)
        info.className = "android.widget.Button"
      }
    }
  }
  private fun buildReceipt() {
    shell = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(18), dp(10), dp(12), dp(8))
      background = shape(paper, 18, Color.parseColor("#DCE0D7"))
      elevation = dp(2).toFloat()
    }
    shell.addView(View(this).apply { background = shape(Color.parseColor("#C7CEC7"), 2); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
      LinearLayout.LayoutParams(dp(28), dp(3)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = dp(9) })
    val heading = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    heading.addView(text("TROTTER / DREAMS", 10f, muted).apply { letterSpacing = 0.13f }, LinearLayout.LayoutParams(0, -2, 1f))
    close = text("×", 25f, muted).apply {
      gravity = Gravity.CENTER; contentDescription = "Dismiss save confirmation"; isEnabled = false
      isClickable = true; isFocusable = true
      setOnClickListener { dismissReceipt() }
    }
    buttonRole(close)
    heading.addView(close, LinearLayout.LayoutParams(dp(44), dp(44)))
    shell.addView(heading)

    val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    thumbnail = ImageView(this).apply {
      scaleType = ImageView.ScaleType.CENTER_CROP
      contentDescription = null
      background = shape(Color.parseColor("#E9EDE7"), 4)
      clipToOutline = true
      setImageDrawable(object : android.graphics.drawable.Drawable() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = muted; style = Paint.Style.STROKE; strokeWidth = dp(1).toFloat() }
        override fun draw(canvas: Canvas) {
          val cx = bounds.exactCenterX(); val cy = bounds.exactCenterY(); val unit = dp(1).toFloat()
          canvas.drawRoundRect(cx - 11 * unit, cy - 13 * unit, cx + 11 * unit, cy + 13 * unit, 3 * unit, 3 * unit, paint)
          val play = Path().apply { moveTo(cx - 3 * unit, cy - 5 * unit); lineTo(cx + 5 * unit, cy); lineTo(cx - 3 * unit, cy + 5 * unit); close() }
          canvas.drawPath(play, paint)
        }
        override fun setAlpha(alpha: Int) { paint.alpha = alpha }
        override fun setColorFilter(filter: android.graphics.ColorFilter?) { paint.colorFilter = filter }
        @Suppress("DEPRECATION") override fun getOpacity() = android.graphics.PixelFormat.TRANSLUCENT
      })
    }
    row.addView(thumbnail, LinearLayout.LayoutParams(dp(46), dp(58)).apply { marginEnd = dp(13) })
    val content = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    val titleRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    title = text("Saving reel…", 24f, serif = true).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
    titleRow.addView(title, LinearLayout.LayoutParams(0, -2, 1f))
    checkmark = text("✓", 17f).apply { alpha = 0f; importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }
    titleRow.addView(checkmark, LinearLayout.LayoutParams(dp(22), -2).apply { marginStart = dp(8) })
    content.addView(titleRow)
    detail = text("", 12f, muted).apply { minLines = 1; setLineSpacing(dp(2).toFloat(), 1f) }
    content.addView(detail, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(6) })
    row.addView(content, LinearLayout.LayoutParams(0, -2, 1f))
    shell.addView(row, LinearLayout.LayoutParams(-1, -2).apply { marginEnd = dp(10) })
    preview = text("Instagram reel", 12f, muted).apply { maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END }
    shell.addView(preview, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(10); marginEnd = dp(12) })

    open = text("View in Dreams", 13f).apply {
      gravity = Gravity.CENTER_VERTICAL; setPadding(0, 0, dp(16), 0)
      isEnabled = false; isClickable = true; isFocusable = true
      setOnClickListener { openDreams() }
    }
    buttonRole(open)
    shell.addView(open, LinearLayout.LayoutParams(-2, dp(44)))
    setContentView(shell)
    val width = minOf(resources.displayMetrics.widthPixels - dp(24), dp(420))
    window.setLayout(width, WindowManager.LayoutParams.WRAP_CONTENT)
    window.attributes = window.attributes.apply { y = dp(12) }
  }

  private fun render(item: JSONObject) {
    receipt = item
    val status = item.optString("status")
    policy.stored(status, now())
    val post = item.optString("sourceUrl").contains("/p/")
    title.text = if (post) "Post saved" else "Reel saved"
    detail.text = when (status) {
      "saved" -> "Saved to Dreams."
      "sign_in" -> "Sign in to add it to your Dreams."
      "failed" -> "Open Dreams to finish saving this reel."
      else -> "Saved on this phone."
    }
    val caption = item.optString("sharedText").replace(Regex("https?://\\S+"), "").trim()
    preview.text = caption.ifBlank { if (post) "Instagram post" else "Instagram reel" }
    open.text = if (status == "sign_in") "Sign in to Trotter" else "View in Dreams"
    open.isEnabled = true
    close.isEnabled = true
    if (!confirmed) {
      confirmed = true
      if (motionEnabled()) {
        checkmark.scaleX = 0.9f; checkmark.scaleY = 0.9f
        checkmark.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(140).setInterpolator(easeOut).start()
      } else checkmark.alpha = 1f
      if (!stopped) shell.performHapticFeedback(if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.VIRTUAL_KEY)
    } else checkmark.alpha = 1f
    scheduleDismissal()
  }

  private fun scheduleDismissal() {
    handler.removeCallbacks(dismissTask)
    if (!stopped && !closing) policy.dismissalDelay(now())?.let { handler.postDelayed(dismissTask, it) }
  }
  private fun poll() {
    if (stopped || isFinishing || isDestroyed || closing || pollInFlight) return
    val id = receiptId ?: return
    handler.removeCallbacks(pollTask)
    pollInFlight = true
    io.execute {
      val item = runCatching { DreamShareStore.receipt(applicationContext, id) }.getOrNull()
      runOnUiThread {
        pollInFlight = false
        if (!stopped && !isFinishing && !isDestroyed && !closing) {
          item?.let { render(it) }
          if (item?.optString("status") in listOf("queued", "uploading")) handler.postDelayed(pollTask, 450)
        }
      }
    }
  }

  private fun dismissReceipt() {
    if (!policy.canDismiss || closing || isFinishing) return
    closing = true
    handler.removeCallbacksAndMessages(null)
    shell.animate().cancel()
    if (motionEnabled()) shell.animate().translationY(shell.translationY.coerceAtLeast(0f) + dp(22)).alpha(0f).setDuration(150).setInterpolator(easeOut).withEndAction { finishImmediately() }.start()
    else finishImmediately()
  }
  @Suppress("DEPRECATION")
  private fun finishImmediately() { super.finish(); overridePendingTransition(0, 0) }

  override fun dispatchTouchEvent(event: MotionEvent): Boolean {
    if (closing) return true
    when (event.actionMasked) {
      MotionEvent.ACTION_OUTSIDE -> { dismissReceipt(); return true }
      MotionEvent.ACTION_DOWN -> {
        policy.interaction(true, now()); scheduleDismissal()
        fingerDownY = event.rawY; fingerDownX = event.rawX; dragging = false
        val bounds = IntArray(2); shell.getLocationOnScreen(bounds)
        if (event.rawX < bounds[0] || event.rawX > bounds[0] + shell.width || event.rawY < bounds[1] || event.rawY > bounds[1] + shell.height) {
          policy.interaction(false, now()); dismissReceipt(); return true
        }
      }
      MotionEvent.ACTION_MOVE -> {
        val distance = event.rawY - fingerDownY
        if (dragging || (policy.canDismiss && !accessibility.isTouchExplorationEnabled && distance > ViewConfiguration.get(this).scaledTouchSlop && distance > abs(event.rawX - fingerDownX))) {
          if (!dragging) {
            dragging = true
            val cancel = MotionEvent.obtain(event).apply { action = MotionEvent.ACTION_CANCEL }
            super.dispatchTouchEvent(cancel); cancel.recycle()
            shell.animate().cancel()
          }
          shell.translationY = distance.coerceAtLeast(0f)
          shell.alpha = (1f - distance / dp(280)).coerceIn(0.45f, 1f)
          return true
        }
      }
      MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
        policy.interaction(false, now())
        if (dragging) {
          dragging = false
          if (event.actionMasked == MotionEvent.ACTION_UP && event.rawY - fingerDownY > dp(42)) dismissReceipt()
          else if (motionEnabled()) shell.animate().translationY(0f).alpha(1f).setDuration(150).setInterpolator(easeOut).start()
          else { shell.translationY = 0f; shell.alpha = 1f }
          scheduleDismissal()
          return true
        }
        scheduleDismissal()
      }
    }
    return super.dispatchTouchEvent(event)
  }

  @Suppress("DEPRECATION")
  override fun onBackPressed() { dismissReceipt() }

  private fun openDreams() {
    val item = receipt ?: return
    if (closing) return
    val uri = Uri.Builder().scheme("trotterv2").authority("dreams")
      .appendQueryParameter("source_url", item.getString("sourceUrl")).appendQueryParameter("receipt_id", item.getString("id"))
    if (item.optInt("itemId") > 0) uri.appendQueryParameter("item_id", item.getInt("itemId").toString())
    startActivity(Intent(this, MainActivity::class.java).setAction(Intent.ACTION_VIEW).setData(uri.build())
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
    closing = true
    finishImmediately()
  }
  private fun sharedText(incoming: Intent): String {
    val parts = mutableListOf<String>()
    listOf(Intent.EXTRA_TEXT, Intent.EXTRA_SUBJECT, Intent.EXTRA_TITLE).forEach { key ->
      incoming.getCharSequenceExtra(key)?.toString()?.takeIf { it.isNotBlank() }?.let { parts.add(it) }
    }
    incoming.clipData?.let { clip -> for (index in 0 until clip.itemCount) clip.getItemAt(index).text?.toString()?.let { parts.add(it) } }
    incoming.data?.toString()?.let { parts.add(it) }
    return parts.distinct().joinToString("\n").take(60000)
  }
  @Suppress("DEPRECATION")
  private fun loadProvidedThumbnail(incoming: Intent) {
    val supplied = if (incoming.action == Intent.ACTION_SEND_MULTIPLE) incoming.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.firstOrNull()
      else incoming.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
    val uri = supplied ?: incoming.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri ?: return
    if (uri.scheme != "content") return
    io.execute {
      runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@runCatching
        val options = BitmapFactory.Options().apply { inSampleSize = maxOf(1, maxOf(bounds.outWidth, bounds.outHeight) / 180) }
        val bitmap = contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
        runOnUiThread { if (!isFinishing && !isDestroyed && bitmap != null) thumbnail.setImageBitmap(bitmap) }
      }
    }
  }
  @Suppress("DEPRECATION")
  override fun onRetainNonConfigurationInstance(): Any? = captureRequest
  override fun onSaveInstanceState(outState: Bundle) {
    val snapshot = policy.snapshot(now())
    outState.putString("receiptId", receiptId)
    outState.putBoolean("captured", snapshot.captured)
    outState.putBoolean("storageFailed", snapshot.storageFailed)
    outState.putString("status", snapshot.status)
    outState.putLong("remainingMs", snapshot.remainingMs)
    outState.putBoolean("confirmed", confirmed)
    super.onSaveInstanceState(outState)
  }
  override fun onWindowFocusChanged(hasFocus: Boolean) {
    super.onWindowFocusChanged(hasFocus)
    policy.visibility(hasFocus && !stopped, now())
    if (::shell.isInitialized) scheduleDismissal()
  }
  override fun onStop() {
    stopped = true; policy.visibility(false, now()); handler.removeCallbacksAndMessages(null); super.onStop()
  }
  override fun onStart() {
    super.onStart(); stopped = false; policy.visibility(window.decorView.hasWindowFocus(), now())
    if (receiptId != null) poll()
    scheduleDismissal()
  }
  override fun onDestroy() {
    accessibility.removeTouchExplorationStateChangeListener(accessibilityListener)
    handler.removeCallbacksAndMessages(null)
    shell.animate().cancel()
    // shutdown(), not shutdownNow(): a capture already in progress must finish durably.
    io.shutdown(); super.onDestroy()
  }
}
