package com.trotter.mobilev2

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import java.util.UUID

class DreamShareModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val bridgeId = UUID.randomUUID().toString()
  override fun getName() = "TrotterDreamShare"
  override fun initialize() { super.initialize(); DreamShareStore.attachBridge(bridgeId) }

  @ReactMethod fun invalidateSession(revision: Int, promise: Promise) {
    try { DreamShareStore.invalidateForBridge(reactApplicationContext, revision, bridgeId); promise.resolve(null) }
    catch (error: Exception) { promise.reject("SHARE_SIGN_OUT", "The share sign-in could not be cleared.", error) }
  }
  @ReactMethod fun configureSession(apiBaseUrl: String, ownerId: Int, token: String, revision: Int, promise: Promise) {
    try {
      DreamShareStore.configureForBridge(reactApplicationContext, apiBaseUrl, ownerId, token, revision, bridgeId)
      DreamShareWorker.enqueue(reactApplicationContext)
      promise.resolve(null)
    } catch (error: Exception) { promise.reject("SHARE_SIGN_IN", "Background sharing could not be enabled.", error) }
  }
  @ReactMethod fun listReceipts(promise: Promise) {
    try {
      val result = Arguments.createArray()
      DreamShareStore.visible(reactApplicationContext).forEach { item ->
        val value = Arguments.createMap()
        listOf("id", "sourceUrl", "sharedText", "status", "message").forEach { key -> if (!item.isNull(key)) value.putString(key, item.getString(key)) }
        listOf("ownerId", "itemId", "dreamId").forEach { key -> if (!item.isNull(key)) value.putInt(key, item.getInt(key)) }
        value.putDouble("createdAt", item.getLong("createdAt").toDouble())
        result.pushMap(value)
      }
      promise.resolve(result)
    } catch (error: Exception) { promise.reject("SHARE_RECEIPTS", "Saved links could not be read.", error) }
  }
  @ReactMethod fun flush(promise: Promise) {
    try { DreamShareWorker.enqueue(reactApplicationContext); promise.resolve(null) }
    catch (error: Exception) { promise.reject("SHARE_RETRY", "Saved links could not be sent yet.", error) }
  }
  @ReactMethod fun retry(id: String, promise: Promise) {
    try { DreamShareStore.retry(reactApplicationContext, id); DreamShareWorker.enqueue(reactApplicationContext, id, restart = true); promise.resolve(null) }
    catch (error: Exception) { promise.reject("SHARE_RETRY", "This link could not be retried yet.", error) }
  }
  @ReactMethod fun acknowledge(id: String, promise: Promise) {
    try { DreamShareStore.acknowledge(reactApplicationContext, id); promise.resolve(null) }
    catch (error: Exception) { promise.reject("SHARE_RECEIPT", "The saved receipt could not be cleared yet.", error) }
  }
}

class DreamSharePackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(DreamShareModule(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
