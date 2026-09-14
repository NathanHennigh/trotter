import React from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";
import * as Haptics from "expo-haptics";

type Preferences = { texture: "classic" | "nasa"; haptics: boolean };
const KEY = "trotter.world-window.preferences.v1";
let current: Preferences = { texture: "classic", haptics: true };
let loaded = false, loadPromise: Promise<void> | undefined;
let pendingPatch: Partial<Preferences> = {};
let writeQueue = Promise.resolve();
const listeners = new Set<(value: Preferences) => void>();
function notify() { listeners.forEach(listener => listener(current)); }
function load() {
  if (!loadPromise) {
    loadPromise = AsyncStorage.getItem(KEY).then(raw => {
      if (raw) {
        const saved = JSON.parse(raw);
        current = { texture: saved.texture === "nasa" ? "nasa" : "classic", haptics: saved.haptics !== false, ...pendingPatch };
      }
    }).catch(() => undefined).then(() => {
      loaded = true; notify();
      if (Object.keys(pendingPatch).length) persist();
      pendingPatch = {};
    });
  }
  return loadPromise;
}
function update(patch: Partial<Preferences>) {
  current = { ...current, ...patch };
  notify();
  if (!loaded) { pendingPatch = { ...pendingPatch, ...patch }; void load(); return; }
  persist();
}
function persist() {
  const serialized = JSON.stringify(current);
  writeQueue = writeQueue.then(() => AsyncStorage.setItem(KEY, serialized)).catch(() => undefined);
}
export function useExperiencePreferences() {
  const [value, setValue] = React.useState(current);
  React.useEffect(() => { listeners.add(setValue); setValue(current); void load(); return () => { listeners.delete(setValue); }; }, []);
  return { ...value, setTexture: (texture: Preferences["texture"]) => update({ texture }), setHaptics: (haptics: boolean) => update({ haptics }) };
}

let lastFeedback = 0;
/** Only meaningful completed selections; no buzz during dragging or on the web. */
export function selectionHaptic(kind: "selection" | "confirmation" | "page" = "selection") {
  if (!loaded || !current.haptics || Platform.OS === "web" || Date.now() - lastFeedback < 70) return;
  lastFeedback = Date.now();
  const response = kind === "page" ? Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light) : Haptics.selectionAsync();
  void response.catch(() => undefined);
}
