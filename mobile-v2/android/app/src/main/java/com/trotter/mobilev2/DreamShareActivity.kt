package com.trotter.mobilev2

import android.app.Activity
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

/** A small native receipt leaves Instagram visible and never starts React just to capture a link. */
class DreamShareActivity : Activity() {
  private val handler = Handler(Looper.getMainLooper())
  private val io = Executors.newSingleThreadExecutor()
  private var receiptId: String? = null
  private var receipt: JSONObject? = null
  private var stopped = false
  private lateinit var title: TextView
  private lateinit var detail: TextView
  private lateinit var preview: TextView
  private lateinit var thumbnail: ImageView
  private lateinit var open: Button
  private lateinit var done: Button
  private var lastStatus: String? = null
  private val ink = Color.parseColor("#31576B")
  private val muted = Color.parseColor("#526975")
  private val paper = Color.parseColor("#FAF8F2")

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    window.setGravity(Gravity.BOTTOM)
    window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
    window.attributes = window.attributes.apply { dimAmount = 0.18f }
    setFinishOnTouchOutside(false)
    buildReceipt()
    receiptId = savedInstanceState?.getString("receiptId")
    val text = sharedText(intent)
    val persisted = receiptId
    io.execute {
      try {
        val captured = persisted?.let { DreamShareStore.receipt(this, it) } ?: DreamShareStore.capture(this, text)
        receiptId = captured.getString("id")
        runOnUiThread {
          if (!isFinishing) { render(captured); setFinishOnTouchOutside(true); poll() }
        }
        DreamShareWorker.enqueue(applicationContext, captured.getString("id"), restart = true)
      } catch (error: Exception) {
        runOnUiThread {
          if (!isFinishing) {
            title.text = "Couldn’t keep this link"
            detail.text = error.message ?: "Please try sharing it again."
            done.isEnabled = true
            open.visibility = View.GONE
            setFinishOnTouchOutside(true)
          }
        }
      }
    }
    loadProvidedThumbnail(intent)
  }

  private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
  private fun shape(color: Int, radius: Int, border: Int? = null) = GradientDrawable().apply {
    setColor(color); cornerRadius = dp(radius).toFloat(); border?.let { setStroke(dp(1), it) }
  }
  private fun text(value: String, size: Float, color: Int = ink, serif: Boolean = false) = TextView(this).apply {
    text = value; textSize = size; setTextColor(color)
    typeface = runCatching { Typeface.createFromAsset(assets, if (serif) "share-fonts/Newsreader-Regular.ttf" else "share-fonts/DMSans-Regular.ttf") }
      .getOrElse { Typeface.create(if (serif) "serif" else "sans-serif", Typeface.NORMAL) }
    includeFontPadding = false
  }
  private fun buildReceipt() {
    val shell = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(24), dp(26), dp(24), dp(22))
      background = shape(paper, 24)
      elevation = dp(3).toFloat()
    }
    shell.addView(text("DREAMS", 11f).apply { letterSpacing = 0.2f }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(17) })
    title = text("Keeping your link…", 30f, serif = true).apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
    shell.addView(title, LinearLayout.LayoutParams(-1, -2))
    detail = text("", 14f, muted).apply { setLineSpacing(dp(3).toFloat(), 1f) }
    shell.addView(detail, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(9); bottomMargin = dp(20) })

    val post = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      setPadding(dp(12), dp(12), dp(12), dp(12))
      background = shape(Color.parseColor("#FFFCF1"), 10, Color.parseColor("#D7DED5"))
    }
    thumbnail = ImageView(this).apply {
      setImageResource(R.mipmap.ic_launcher)
      scaleType = ImageView.ScaleType.CENTER_CROP
      contentDescription = null
      background = shape(Color.parseColor("#E9EEE7"), 6)
      clipToOutline = true
    }
    post.addView(thumbnail, LinearLayout.LayoutParams(dp(48), dp(60)).apply { marginEnd = dp(13) })
    val postText = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    postText.addView(text("INSTAGRAM", 10f, muted).apply { letterSpacing = 0.13f }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) })
    preview = text("Shared reel", 14f).apply { maxLines = 3; ellipsize = android.text.TextUtils.TruncateAt.END }
    postText.addView(preview)
    post.addView(postText, LinearLayout.LayoutParams(0, -2, 1f))
    shell.addView(post, LinearLayout.LayoutParams(-1, -2))

    val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
    open = Button(this).apply {
      text = "View in Dreams"; isAllCaps = false; textSize = 14f; setTextColor(ink)
      background = shape(Color.TRANSPARENT, 10, Color.parseColor("#C6D0CA"))
      minimumWidth = 0; minimumHeight = 0; setPadding(dp(8), 0, dp(8), 0)
      isEnabled = false
      setOnClickListener { openDreams() }
    }
    done = Button(this).apply {
      text = "Done"; isAllCaps = false; textSize = 14f; setTextColor(paper)
      background = shape(ink, 10); minimumWidth = 0; minimumHeight = 0
      isEnabled = false; setOnClickListener { finish() }
    }
    actions.addView(open, LinearLayout.LayoutParams(0, dp(48), 1.3f).apply { marginEnd = dp(10) })
    actions.addView(done, LinearLayout.LayoutParams(0, dp(48), 1f))
    shell.addView(actions, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(22) })
    setContentView(shell)
    val width = minOf(resources.displayMetrics.widthPixels - dp(24), dp(420))
    window.setLayout(width, WindowManager.LayoutParams.WRAP_CONTENT)
    window.attributes = window.attributes.apply { y = dp(16) }
  }

  private fun render(item: JSONObject) {
    receipt = item
    val status = item.optString("status")
    val copy = when (status) {
      "saved" -> "Saved to Dreams" to "Places will appear as they’re found."
      "uploading" -> "Saving to Dreams…" to "You can return to Instagram."
      "sign_in" -> "Link kept" to "Sign in to send it to your Dreams."
      "failed" -> "Link kept" to "Open Dreams to try sending it again."
      else -> "Link kept" to "It will send when a connection is available."
    }
    if (lastStatus != status) { title.text = copy.first; detail.text = copy.second; lastStatus = status }
    val caption = item.optString("sharedText").replace(Regex("https?://\\S+"), "").trim()
    preview.text = caption.ifBlank { if (item.optString("sourceUrl").contains("/p/")) "Instagram post" else "Instagram reel" }
    open.text = if (status == "sign_in") "Sign in to Trotter" else "View in Dreams"
    open.isEnabled = true
    done.isEnabled = true
  }

  private fun poll() {
    if (stopped || isFinishing) return
    val id = receiptId ?: return
    io.execute {
      val item = runCatching { DreamShareStore.receipt(this, id) }.getOrNull()
      runOnUiThread {
        if (!stopped && !isFinishing) {
          item?.let { render(it) }
          if (item?.optString("status") in listOf("queued", "uploading")) handler.postDelayed({ poll() }, 450)
        }
      }
    }
  }
  private fun openDreams() {
    val item = receipt ?: return
    val uri = Uri.Builder().scheme("trotterv2").authority("dreams")
      .appendQueryParameter("source_url", item.getString("sourceUrl")).appendQueryParameter("receipt_id", item.getString("id"))
    if (item.optInt("itemId") > 0) uri.appendQueryParameter("item_id", item.getInt("itemId").toString())
    startActivity(Intent(this, MainActivity::class.java).setAction(Intent.ACTION_VIEW).setData(uri.build())
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
    finish()
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
        runOnUiThread { if (!isFinishing && bitmap != null) thumbnail.setImageBitmap(bitmap) }
      }
    }
  }
  override fun onSaveInstanceState(outState: Bundle) { outState.putString("receiptId", receiptId); super.onSaveInstanceState(outState) }
  override fun onStop() { stopped = true; handler.removeCallbacksAndMessages(null); super.onStop() }
  override fun onStart() { super.onStart(); stopped = false; if (receiptId != null) poll() }
  override fun onDestroy() { handler.removeCallbacksAndMessages(null); io.shutdown(); super.onDestroy() }
}
