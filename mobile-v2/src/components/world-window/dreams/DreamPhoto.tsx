import React from "react";
import { Image, Platform, StyleSheet, Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";
import type { DreamItem } from "../../../services/dreams";
import {
  getApiBaseUrl,
  getAuthRevision,
  getStoredToken,
  subscribeAuthToken,
} from "../../../services/travelTrips";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWIcon } from "../WorldWindowUI";
import { placeSymbol, symbolPaths } from "./placeSymbols";
import { findCountryArtwork } from "./countryArtwork";
import { resolveDreamThumbnail } from "./dreamImageSource";

export function PlaceSymbol({
  category,
  size = 26,
  color = colors.blue,
}: {
  category: string;
  size?: number;
  color?: string;
}) {
  return (
    <Svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color}
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      accessibilityElementsHidden
    >
      {symbolPaths[placeSymbol(category)].map((d, index) => (
        <Path key={index} d={d} />
      ))}
    </Svg>
  );
}

export function DreamPhoto({
  item,
  compact = false,
  fallbackCountry,
  artworkForCountry,
}: {
  item?: DreamItem;
  compact?: boolean;
  fallbackCountry?: string;
  /** Opt in only for country postcard covers, never individual saved places. */
  artworkForCountry?: string;
}) {
  const [failedThumbnail, setFailedThumbnail] = React.useState<string>(),
    [failedArtwork, setFailedArtwork] = React.useState<string>(),
    [webImage, setWebImage] = React.useState<{ key: string; uri: string }>();
  const revision = React.useSyncExternalStore(subscribeAuthToken, getAuthRevision, getAuthRevision);
  const base = getApiBaseUrl(),
    token = getStoredToken();
  const candidate = findCountryArtwork(artworkForCountry);
  const artwork = candidate && candidate.code !== failedArtwork ? candidate : undefined;
  const thumbnail = resolveDreamThumbnail(item?.thumbnailUrl, base);
  const uri = thumbnail?.uri, privateImage = thumbnail?.privateImage ?? false;
  const imageKey = uri ? `${revision}:${uri}` : undefined;
  React.useEffect(() => {
    setWebImage(undefined);
    // Local artwork neither needs nor starts an authenticated reel request.
    if (artwork || Platform.OS !== "web" || !uri || !privateImage || !imageKey || !token) return;
    let live = true,
      objectUrl: string | undefined;
    const controller = new AbortController();
    void fetch(uri, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Image unavailable");
        const blob = await response.blob();
        if (live && revision === getAuthRevision()) {
          objectUrl = URL.createObjectURL(blob);
          setWebImage({ key: imageKey, uri: objectUrl });
        }
      })
      .catch(() => {
        if (live && revision === getAuthRevision()) setFailedThumbnail(imageKey);
      });
    return () => {
      live = false;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [uri, privateImage, token, revision, imageKey, artwork?.code]);
  const imageUri = privateImage && !token
    ? undefined
    : Platform.OS === "web" && privateImage
      ? (webImage && webImage.key === imageKey ? webImage.uri : undefined)
      : uri;
  const renderedKey = imageUri ? `${imageKey}:${imageUri}` : imageKey;
  return (
    <View style={s.surface}>
      {artwork ? (
        <Image
          key={`country:${artwork.code}`}
          accessibilityLabel={`${artwork.country} travel photograph`}
          source={artwork.source}
          style={s.image}
          resizeMode="cover"
          onError={() => setFailedArtwork(artwork.code)}
        />
      ) : imageUri && failedThumbnail !== renderedKey ? (
        <Image
          key={renderedKey}
          accessibilityLabel={item?.placeName || "Saved travel photo"}
          source={{
            uri: imageUri,
            ...(privateImage && token && Platform.OS !== "web"
              ? { headers: { Authorization: `Bearer ${token}` } }
              : {}),
          }}
          style={s.image}
          resizeMode="cover"
          onError={() => setFailedThumbnail(renderedKey)}
        />
      ) : artworkForCountry ? (
        <View style={s.countryPaper} />
      ) : (
        <View style={s.fallback}>
          {fallbackCountry ? (
            <>
              <View pointerEvents="none" style={StyleSheet.absoluteFill}>
                {Array.from({ length: 8 }, (_, i) => (
                  <View
                    key={i}
                    style={{
                      position: "absolute",
                      left: 0,
                      right: 0,
                      top: 35 + i * 36,
                      height: 1,
                      backgroundColor: "#c9d4c93d",
                    }}
                  />
                ))}
              </View>
              <WWIcon name="globe" size={48} color={colors.blue} />
              <Text style={s.countryFallback}>{fallbackCountry}</Text>
            </>
          ) : (
            <View style={compact ? s.smallFrame : s.frame}>
              <PlaceSymbol
                category={item?.category || "unknown"}
                size={compact ? 29 : 48}
              />
            </View>
          )}
        </View>
      )}
    </View>
  );
}
const s = StyleSheet.create({
  surface: { flex: 1, backgroundColor: colors.paperDeep },
  // Bundled images carry intrinsic dimensions. Explicit bounds keep those
  // dimensions from overriding the postcard frame in native and web layouts.
  image: { ...StyleSheet.absoluteFillObject, width: "100%", height: "100%" },
  // A country with no usable photo keeps its printed destination on plain
  // blue paper; a single saved place's category must not represent the country.
  countryPaper: { flex: 1, backgroundColor: colors.dashboardSoft },
  fallback: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#e8ede2",
    gap: 14,
  },
  countryFallback: {
    fontFamily: fonts.display,
    fontStyle: "italic",
    fontSize: 21,
    lineHeight: 26,
    color: colors.blue,
    textAlign: "center",
    paddingHorizontal: 12,
  },
  frame: {
    width: 90,
    height: 90,
    borderWidth: 1,
    borderColor: "#c6cfc5",
    alignItems: "center",
    justifyContent: "center",
    transform: [{ rotate: "-4deg" }],
  },
  smallFrame: {
    width: 42,
    height: 51,
    borderWidth: 1,
    borderColor: "#b4c1ad",
    alignItems: "center",
    justifyContent: "center",
  },
});
