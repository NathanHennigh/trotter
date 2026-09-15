package com.trotter.mobilev2

import android.graphics.RenderEffect
import android.graphics.Shader
import android.os.Build
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.ReactPackage
import com.facebook.react.module.annotations.ReactModule
import com.facebook.react.uimanager.ThemedReactContext
import com.facebook.react.uimanager.ViewManager
import com.facebook.react.uimanager.annotations.ReactProp
import com.facebook.react.views.view.ReactViewGroup
import com.facebook.react.views.view.ReactViewManager
import kotlin.math.roundToInt

/** The retained screen tree is blurred in place; no screenshots or child reparenting. */
private class BlurBackground(context: ThemedReactContext) : ReactViewGroup(context) {
  var radius = 0f
  private var effectRadius = -1
  private var effect: RenderEffect? = null

  fun applyBlur() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
    val pixels = (radius * resources.displayMetrics.density * 10).roundToInt()
    if (pixels != effectRadius) {
      effectRadius = pixels
      effect = if (pixels > 0) RenderEffect.createBlurEffect(
        pixels / 10f, pixels / 10f, Shader.TileMode.CLAMP
      ) else null
    }
    // BaseViewManager clears standard layer effects after every property update.
    // Reapply our cached effect after that transaction, including Animated updates.
    setRenderEffect(effect)
  }
}

@ReactModule(name = TrotterBlurBackgroundManager.NAME)
class TrotterBlurBackgroundManager : ReactViewManager() {
  companion object { const val NAME = "TrotterBlurBackground" }
  override fun getName() = NAME
  override fun createViewInstance(context: ThemedReactContext): ReactViewGroup = BlurBackground(context)

  @ReactProp(name = "blurRadius", defaultFloat = 0f)
  fun setBlurRadius(view: ReactViewGroup, radius: Float) {
    (view as BlurBackground).radius = if (radius.isFinite()) radius.coerceIn(0f, 8f) else 0f
  }

  override fun onAfterUpdateTransaction(view: ReactViewGroup) {
    super.onAfterUpdateTransaction(view)
    (view as BlurBackground).applyBlur()
  }
}

class TrotterBlurPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = emptyList()
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> =
    listOf(TrotterBlurBackgroundManager())
}
