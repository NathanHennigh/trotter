package com.trotter.mobilev2

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle

import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

import expo.modules.ReactActivityDelegateWrapper

class MainActivity : ReactActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    // Set the theme to AppTheme BEFORE onCreate to support
    // coloring the background, status bar, and navigation bar.
    // This is required for expo-splash-screen.
    setTheme(R.style.AppTheme);
    intent = intent.asTrotterShareIntent()
    super.onCreate(null)
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent.asTrotterShareIntent())
    setIntent(intent.asTrotterShareIntent())
  }

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "main"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate {
    return ReactActivityDelegateWrapper(
          this,
          BuildConfig.IS_NEW_ARCHITECTURE_ENABLED,
          object : DefaultReactActivityDelegate(
              this,
              mainComponentName,
              fabricEnabled
          ){})
  }

  /**
    * Align the back button behavior with Android S
    * where moving root activities to background instead of finishing activities.
    * @see <a href="https://developer.android.com/reference/android/app/Activity#onBackPressed()">onBackPressed</a>
    */
  override fun invokeDefaultOnBackPressed() {
      if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.R) {
          if (!moveTaskToBack(false)) {
              // For non-root activities, use the default implementation to finish them.
              super.invokeDefaultOnBackPressed()
          }
          return
      }

      // Use the default back button implementation on Android S
      // because it's doing more than [Activity.moveTaskToBack] in fact.
      super.invokeDefaultOnBackPressed()
  }

  private fun Intent.asTrotterShareIntent(): Intent {
    if (action != Intent.ACTION_SEND && action != Intent.ACTION_SEND_MULTIPLE) return this
    val sharedText = extractSharedText() ?: return this
    val instagramUrl = sharedText.extractInstagramUrl() ?: sharedText.extractFirstUrl()
    val shareUri = Uri.Builder()
      .scheme("trotterv2")
      .authority("share")
      .appendQueryParameter("url", instagramUrl ?: sharedText)
      .appendQueryParameter("text", sharedText)
      .build()

    return Intent(Intent.ACTION_VIEW, shareUri).apply {
      addCategory(Intent.CATEGORY_DEFAULT)
      addCategory(Intent.CATEGORY_BROWSABLE)
      flags = this@asTrotterShareIntent.flags
    }
  }

  private fun Intent.extractSharedText(): String? {
    val directText = getStringExtra(Intent.EXTRA_TEXT)
      ?: getStringExtra(Intent.EXTRA_SUBJECT)
      ?: getStringExtra(Intent.EXTRA_TITLE)
    if (!directText.isNullOrBlank()) return directText

    val clip = clipData ?: return null
    val parts = mutableListOf<String>()
    for (index in 0 until clip.itemCount) {
      val text = clip.getItemAt(index).coerceToText(this@MainActivity)?.toString()
      if (!text.isNullOrBlank()) parts.add(text)
    }
    return parts.joinToString("\n").takeIf { it.isNotBlank() }
  }

  private fun String.extractInstagramUrl(): String? {
    return Regex("https?://(?:www\\.)?instagram\\.com/\\S+", RegexOption.IGNORE_CASE)
      .find(this)
      ?.value
      ?.trimEnd('.', ',', ')')
  }

  private fun String.extractFirstUrl(): String? {
    return Regex("https?://\\S+", RegexOption.IGNORE_CASE)
      .find(this)
      ?.value
      ?.trimEnd('.', ',', ')')
  }
}
