import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { WebView } from "react-native-webview";
import { SvgXml } from "react-native-svg";
import { colors, fonts } from "../../../theme/trotterTheme";
import { passportDocument, scriptJSON } from "./passport-document";
import { passportClosedCoverFrame, passportPose, passportViewportHeight } from "./passport-cover";
import { passportCoverFace } from "./passport-cover-face";
import { preparePassportPayload, type BookPayload } from "./passport-payload";
import type { PassportArchive } from "./passport-model";
import { selectionHaptic } from "../../../utils/experiencePreferences";

type BookState = { spread: number; closed: boolean };
type Props = {
  archive: PassportArchive;
  width: number;
  onCountry: (code: string) => void;
  onInteractionChange?: (active: boolean) => void;
  earned?: { key: string; codes: string[] };
  visible?: boolean;
};
export function PassportBook({
  archive,
  width,
  onCountry,
  onInteractionChange,
  earned,
  visible = true,
}: Props) {
  const drawingWidth = Number.isFinite(width) ? Math.max(1, width) : 1;
  const viewportHeight = useMemo(() => passportViewportHeight(drawingWidth), [drawingWidth]);
  const coverFrame = useMemo(() => passportClosedCoverFrame(drawingWidth), [drawingWidth]);
  const coverArtwork = useMemo(() => passportCoverFace(drawingWidth), [drawingWidth]);
  const closedHeight = useMemo(() => {
    const pose = passportPose(0, drawingWidth);
    return Math.ceil(drawingWidth * pose.height / pose.width);
  }, [drawingWidth]);
  const [html, setHtml] = useState<string | null>(null),
    [height, setHeight] = useState(closedHeight),
    [renderReady, setRenderReady] = useState(false),
    [error, setError] = useState(false),
    [attempt, setAttempt] = useState(0);
  const webview = useRef<WebView>(null),
    iframe = useRef<HTMLIFrameElement>(null),
    payload = useRef<BookPayload | null>(null),
    sentPayload = useRef<BookPayload | null>(null),
    loaded = useRef(false),
    openWhenReady = useRef(false);
  const state = useRef<BookState>({ spread: 0, closed: true }),
    initial = useRef<string | null>(null),
    mounted = useRef(true);
  const latest = useRef({ onCountry, onInteractionChange, archive });
  latest.current = { onCountry, onInteractionChange, archive };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      latest.current.onInteractionChange?.(false);
    };
  }, []);
  const sendPayload = useCallback(() => {
    if (
      !payload.current ||
      !loaded.current ||
      sentPayload.current === payload.current
    )
      return;
    if (Platform.OS === "web")
      iframe.current?.contentWindow?.postMessage(
        { type: "passport-update", payload: payload.current },
        "*",
      );
    else
      webview.current?.injectJavaScript(
        `window.updatePassport&&window.updatePassport(${scriptJSON(payload.current)});true;`,
      );
    sentPayload.current = payload.current;
  }, []);
  const openCover = useCallback(() => {
    if (Platform.OS === "web")
      iframe.current?.contentWindow?.postMessage({ type: "passport-open" }, "*");
    else webview.current?.injectJavaScript("window.openPassport&&window.openPassport();true;");
  }, []);
  useEffect(() => {
    if (!renderReady || !openWhenReady.current) return;
    openWhenReady.current = false;
    openCover();
  }, [renderReady, openCover]);
  useEffect(() => {
    let cancelled = false;
    preparePassportPayload(archive)
      .then((next) => {
        if (cancelled) return;
        payload.current = { ...next, state: state.current, earned, visible };
        setError(false);
        if (!initial.current) {
          const document = passportDocument(payload.current);
          initial.current = document;
          sentPayload.current = payload.current;
          setHtml(document);
        } else sendPayload();
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [archive, attempt, sendPayload, earned, visible]);
  const message = useCallback((data: unknown) => {
    if (!mounted.current || !data || typeof data !== "object") return;
    const value = data as Record<string, unknown>;
    if (value.source !== "trotter-passport") return;
    if (value.type === "page-complete") selectionHaptic('page');
    if (
      value.type === "size" &&
      typeof value.height === "number" &&
      Number.isFinite(value.height) &&
      value.height >= 100 &&
      value.height <= 1200
    )
      setHeight(value.height);
    if (value.type === "gesture")
      latest.current.onInteractionChange?.(value.active === true);
    if (
      value.type === "state" &&
      typeof value.spread === "number" &&
      Number.isInteger(value.spread) &&
      value.spread >= 0 &&
      typeof value.closed === "boolean"
    )
      state.current = { spread: value.spread, closed: value.closed };
    if (
      value.type === "country" &&
      typeof value.code === "string" &&
      latest.current.archive.arrivals.some(
        (a) => (a.travelCountryKey ?? a.country) === value.code,
      )
    )
      latest.current.onCountry(value.code);
    if (value.type === "error") setError(true);
    if (value.type === "ready") {
      setError(false);
      setRenderReady(true);
    }
  }, []);
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const listener = (event: MessageEvent) => {
      if (event.source === iframe.current?.contentWindow) message(event.data);
    };
    window.addEventListener("message", listener);
    return () => window.removeEventListener("message", listener);
  }, [message]);
  const source = useMemo(
    () => ({ html: html ?? "", baseUrl: "https://trotter.local/" }),
    [html],
  );
  const onLoad = () => {
    loaded.current = true;
    sendPayload();
  };
  const retry = () => {
    loaded.current = false;
    initial.current = null;
    sentPayload.current = null;
    setHtml(null);
    setRenderReady(false);
    setError(false);
    setAttempt((value) => value + 1);
  };
  return (
    // Native/WebView layout crosses threads. Keep its drawing surface large
    // enough for every pose; size messages adjust only the surrounding flow.
    <View style={{ width: drawingWidth, height: renderReady ? height : closedHeight, overflow: "visible" }}>
      {html && (Platform.OS === "web" ? (
        React.createElement("iframe", {
          ref: iframe,
          title: "Interactive travel passport",
          srcDoc: html,
          sandbox: "allow-scripts allow-same-origin",
          onLoad,
          style: {
            display: "block",
            position: "absolute",
            left: 0,
            top: 0,
            flex: "none",
            border: 0,
            background: "transparent",
            opacity: renderReady ? 1 : 0,
            width: drawingWidth,
            height: viewportHeight,
          },
        })
      ) : (
        <WebView
          ref={webview}
          source={source}
          originWhitelist={["https://trotter.local", "about:*"]}
          onLoad={onLoad}
          onMessage={(event) => {
            try {
              message(JSON.parse(event.nativeEvent.data));
            } catch {
              /* Ignore unrelated WebView messages. */
            }
          }}
          onShouldStartLoadWithRequest={(request) =>
            request.url === "about:blank" ||
            request.url === "https://trotter.local/" ||
            request.url.startsWith("data:text/html")
          }
          onError={() => {
            setError(true);
            latest.current.onInteractionChange?.(false);
          }}
          javaScriptEnabled
          scrollEnabled={false}
          nestedScrollEnabled={false}
          bounces={false}
          overScrollMode="never"
          domStorageEnabled={false}
          allowFileAccess={false}
          allowUniversalAccessFromFileURLs={false}
          mixedContentMode="never"
          setSupportMultipleWindows={false}
          showsVerticalScrollIndicator={false}
          androidLayerType="hardware"
          style={[styles.webview, { width: drawingWidth, height: viewportHeight, opacity: renderReady ? 1 : 0 }]}
          containerStyle={[styles.webview, { width: drawingWidth, height: viewportHeight, opacity: renderReady ? 1 : 0 }]}
          onTouchEnd={() => latest.current.onInteractionChange?.(false)}
          onTouchCancel={() => latest.current.onInteractionChange?.(false)}
        />
      ))}
      {!renderReady && (
        <Pressable
          testID="passport-loading-cover"
          accessibilityRole="button"
          accessibilityLabel={error ? "Retry loading passport" : "Open passport when ready"}
          onPress={() => {
            if (error) retry();
            else openWhenReady.current = true;
          }}
          style={[
            styles.loadingCover,
            { left: coverFrame.left, top: coverFrame.top, width: coverFrame.width, height: coverFrame.height },
          ]}
        >
          <SvgXml xml={coverArtwork} width={coverFrame.width} height={coverFrame.height} pointerEvents="none" accessible={false} />
        </Pressable>
      )}
      {error ? (
        <Pressable
          accessibilityRole="button"
          onPress={retry}
          style={[styles.retry, styles.overlayRetry]}
        >
          <Text style={styles.error}>Reload passport</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
const styles = StyleSheet.create({
  // Override react-native-webview's internal flex:1 on both native layers.
  webview: { position: "absolute", left: 0, top: 0, flex: 0, flexGrow: 0, flexShrink: 0, backgroundColor: "transparent" },
  loadingCover: {
    position: "absolute",
  },
  retry: { padding: 12 },
  overlayRetry: {
    position: "absolute",
    bottom: 12,
    alignSelf: "center",
    backgroundColor: colors.paper,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  error: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.ink },
});
