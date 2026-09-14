import React from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import Svg, { Path } from "react-native-svg";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { PressFeedback } from "../components/world-window/motion";
import { WWEmblem } from "../components/world-window/WorldWindowUI";
import { useTravelTrips } from "../services/travelTrips";
import { colors, fonts } from "../theme/trotterTheme";

export function AuthScreen() {
  const insets = useSafeAreaInsets();
  const { height } = useWindowDimensions();
  const { authStatus, status, error, signIn, signOut, signOutPending, retryAuth } =
    useTravelTrips();
  const [clearing, setClearing] = React.useState(false);
  const retrySignOut = async () => {
    if (clearing) return;
    setClearing(true);
    try { await signOut(); } finally { setClearing(false); }
  };
  const busy = authStatus === "loading";
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        {
          minHeight: height,
          paddingTop: insets.top + 32,
          paddingBottom: insets.bottom + 24,
        },
      ]}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.brand}>
        <WWEmblem size={18.5} color={colors.blue} />
        <Text style={styles.wordmark}>TROTTER</Text>
      </View>
      <View style={styles.story}>
        <View
          style={styles.window}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        >
          <WWEmblem size={98} color={colors.blue} />
        </View>
        <Text style={styles.title}>Welcome to Trotter</Text>
        <Text style={styles.description}>
          Sign in with the Google account that receives your flight
          confirmations.
        </Text>
      </View>
      <View style={styles.actions}>
        {error ? (
          <Text
            accessibilityRole="alert"
            accessibilityLiveRegion="polite"
            style={styles.error}
          >
            {error}
          </Text>
        ) : null}
        {signOutPending ? (
          <PressFeedback
            accessibilityRole="button"
            accessibilityState={{ disabled: clearing, busy: clearing }}
            disabled={clearing}
            onPress={() => void retrySignOut()}
            style={styles.googleButton}
          >
            {clearing ? <ActivityIndicator color={colors.blue} /> : null}
            <Text style={styles.googleLabel}>{clearing ? "Finishing sign out…" : "Retry sign out"}</Text>
          </PressFeedback>
        ) : busy ? (
          <View accessibilityLiveRegion="polite" style={styles.loading}>
            <ActivityIndicator color={colors.blue} />
            <Text style={styles.loadingText}>Connecting your account…</Text>
          </View>
        ) : (
          <PressFeedback
            accessibilityRole="button"
            onPress={() => void signIn()}
            style={styles.googleButton}
          >
            <GoogleMark />
            <Text style={styles.googleLabel}>Continue with Google</Text>
          </PressFeedback>
        )}
        {signOutPending ? null : busy ? (
          <PressFeedback
            accessibilityRole="button"
            onPress={() => void signOut()}
            style={styles.textButton}
          >
            <Text style={styles.textButtonLabel}>Cancel</Text>
          </PressFeedback>
        ) : status === "error" ? (
          <PressFeedback
            accessibilityRole="button"
            onPress={() => void retryAuth()}
            style={styles.textButton}
          >
            <Text style={styles.textButtonLabel}>Try connection again</Text>
          </PressFeedback>
        ) : null}
        <Text style={styles.privacy}>
          Trotter uses read-only Gmail access to build your private travel
          archive.
        </Text>
      </View>
    </ScrollView>
  );
}

function GoogleMark() {
  return (
    <Svg width={20} height={20} viewBox="0 0 24 24" accessibilityElementsHidden>
      <Path
        fill="#4285F4"
        d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.61 4.61 0 0 1-2 3.02v2.52h3.24c1.9-1.75 2.98-4.33 2.98-7.37Z"
      />
      <Path
        fill="#34A853"
        d="M12 22c2.7 0 4.96-.9 6.62-2.4l-3.24-2.52c-.9.6-2.05.96-3.38.96-2.6 0-4.8-1.76-5.59-4.12H3.07v2.6A10 10 0 0 0 12 22Z"
      />
      <Path
        fill="#FBBC05"
        d="M6.41 13.92a6 6 0 0 1 0-3.84v-2.6H3.07a10 10 0 0 0 0 9.04l3.34-2.6Z"
      />
      <Path
        fill="#EA4335"
        d="M12 5.96c1.47 0 2.79.5 3.83 1.51l2.87-2.87A9.62 9.62 0 0 0 12 2a10 10 0 0 0-8.93 5.48l3.34 2.6A5.99 5.99 0 0 1 12 5.96Z"
      />
    </Svg>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  content: {
    paddingHorizontal: 24,
    alignItems: "center",
    justifyContent: "space-between",
    gap: 26,
  },
  brand: { flexDirection: "row", alignItems: "center", minHeight: 25, gap: 7 },
  wordmark: {
    color: colors.blue,
    fontFamily: fonts.sansSemi,
    fontSize: 15,
    letterSpacing: 1.8,
  },
  story: { alignItems: "center", width: "100%", maxWidth: 400 },
  window: {
    width: 160,
    height: 150,
    marginBottom: 26,
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    color: colors.blue,
    fontFamily: fonts.display,
    fontSize: 38,
    lineHeight: 42,
    letterSpacing: -0.7,
    textAlign: "center",
  },
  description: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    lineHeight: 23,
    textAlign: "center",
    marginTop: 16,
    maxWidth: 310,
  },
  actions: { width: "100%", maxWidth: 380, gap: 10 },
  googleButton: {
    minHeight: 54,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
    borderRadius: 3,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    paddingHorizontal: 16,
  },
  googleLabel: { color: colors.ink, fontFamily: fonts.sansSemi, fontSize: 14 },
  loading: {
    minHeight: 54,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  loadingText: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.mutedInk,
  },
  privacy: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    lineHeight: 17,
    textAlign: "center",
    marginTop: 4,
  },
  error: {
    color: colors.redDeep,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
    marginBottom: 6,
  },
  textButton: {
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 16,
  },
  textButtonLabel: {
    color: colors.blue,
    fontFamily: fonts.sansSemi,
    fontSize: 13,
  },
});
