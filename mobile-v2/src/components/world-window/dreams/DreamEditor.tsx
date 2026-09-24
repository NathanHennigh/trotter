import React from "react";
import {
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { DreamItem, DreamItemCategory } from "../../../services/dreams";
import { colors, fonts } from "../../../theme/trotterTheme";
import { WWButton, WWIcon } from "../WorldWindowUI";
import { fitDisplayFont } from "../displayTextFit";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { DreamPlacesMap } from "./DreamPlacesMap";
import type { MapPoint } from "../trips/tripPresentation";
import { categoryLabel, dreamLocationType, exactMapPoint, safeWebUrl } from "./dreamPresentation";
import { dreamCardTitle } from "./dreamCardPresentation";
import { DreamPhoto } from "./DreamPhoto";
import { canFindLocation, locationExplanation } from "./locationPresentation";
import { dreamProcessingState } from "./dreamProcessing";
import { useLiveDreamLocation } from "./useLiveDreamLocation";
import { countryRegion } from "./countryRegion";
import { draftFingerprint, draftFromItem } from "./dreamDraft";
import { PressFeedback as Pressable, useReducedMotion } from "../motion";
import { selectionHaptic } from "../../../utils/experiencePreferences";

const categories: DreamItemCategory[] = [
  "restaurant",
  "cafe",
  "bar",
  "hotel",
  "attraction",
  "activity",
  "beach",
  "shopping",
  "nature",
  "museum",
  "event",
  "unknown",
];
export function DreamEditor({
  item,
  points,
  onClose,
  onSave,
  onDelete,
  onRetry,
  onLocate,
  sourceCount = 1,
  onShowSource,
  initialMode = "view",
  visible = true,
  onCloseRequestChange,
}: {
  item: DreamItem;
  points: MapPoint[];
  onClose: () => void;
  onSave: (id: string, patch: Partial<DreamItem>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onRetry: () => void;
  onLocate?: (id: string) => Promise<void>;
  sourceCount?: number;
  onShowSource?: () => void;
  initialMode?: "view" | "edit";
  visible?: boolean;
  onCloseRequestChange?: (handler: (() => void) | null) => void;
}) {
  const insets = useSafeAreaInsets();
  const { width, height = 800, fontScale } = useWindowDimensions();
  const displayName = dreamCardTitle(item);
  const sourceTitle = !item.placeName?.trim() && item.coordinatePrecision !== "area";
  const titleSize = fitDisplayFont(displayName, sourceTitle ? 28 : 34, Math.min(getMobileVisualWidth(width) - 64, 512), fontScale);
  const mounted = React.useRef(true), closed = React.useRef(false), running = React.useRef(false);
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const close = () => {
    if (closed.current) return;
    closed.current = true;
    onClose();
  };
  const reducedMotion = useReducedMotion();
  const [editing, setEditing] = React.useState(initialMode === "edit"),
    [discarding, setDiscarding] = React.useState(false),
    [success, setSuccess] = React.useState<string>(),
    [confirmDelete, setConfirmDelete] = React.useState(false),
    [busy, setBusy] = React.useState(false),
    [error, setError] = React.useState<string>(),
    [placing, setPlacing] = React.useState(false),
    [menuOpen, setMenuOpen] = React.useState(false),
    [expandedSummary, setExpandedSummary] = React.useState(false);
  const [name, setName] = React.useState(item.placeName || ""),
    [city, setCity] = React.useState(item.city || ""),
    [country, setCountry] = React.useState(item.country || ""),
    [region, setRegion] = React.useState(item.regionOrNeighborhood || ""),
    [summary, setSummary] = React.useState(item.summary),
    [tags, setTags] = React.useState(item.tags.join(", ")),
    [maps, setMaps] = React.useState(item.googleMapsUrl || ""),
    [category, setCategory] = React.useState(item.category);
  const mapsBaseline = React.useRef(item.googleMapsUrl || "");
  const draftBaseline = React.useRef(draftFingerprint(draftFromItem(item)));
  const currentDraft = draftFingerprint({ name, city, country, region, summary, tags, maps, category });
  const requestClose = () => {
    // The request is already submitted; closing cannot cancel or discard it.
    if (running.current) { close(); return; }
    if (menuOpen) { setMenuOpen(false); return; }
    if (discarding) { setDiscarding(false); return; }
    if (confirmDelete) { setConfirmDelete(false); return; }
    if (editing && currentDraft !== draftBaseline.current) { setDiscarding(true); return; }
    close();
  };
  const closeRequest = React.useRef(requestClose);
  closeRequest.current = requestClose;
  React.useEffect(() => {
    onCloseRequestChange?.(visible ? () => closeRequest.current() : null);
    return () => onCloseRequestChange?.(null);
  }, [visible, onCloseRequestChange]);
  const overview = React.useMemo(() => countryRegion(country), [country]);
  const liveLocation = useLiveDreamLocation(item, visible && !editing);
  const locationItem = liveLocation.details ? { ...item, ...liveLocation.details } : item;
  React.useEffect(() => {
    if (!editing && !placing) {
      mapsBaseline.current = item.googleMapsUrl || "";
      setMaps(mapsBaseline.current);
    }
  }, [item.googleMapsUrl, editing, placing]);
  const point = exactMapPoint({
    ...item,
    googleMapsUrl: maps,
    ...(maps !== item.googleMapsUrl
      ? { latitude: undefined, longitude: undefined, locationProvider: undefined, coordinatePrecision: "place" as const }
      : {}),
  });
  const liveCandidate = liveLocation.details && ["resolved", "manual"].includes(liveLocation.details.locationStatus ?? "")
    ? liveLocation.details.locationCandidates.find(candidate => candidate.id === liveLocation.details?.locationPlaceId) : undefined;
  const shownPoint = editing ? point : liveLocation.details && locationItem.locationProvider === "google_places"
    ? (liveCandidate ? exactMapPoint({ ...locationItem, latitude: liveCandidate.latitude, longitude: liveCandidate.longitude }) : undefined)
    : point;
  const mapsUrl = liveCandidate?.googleMapsUrl || item.googleMapsUrl;
  const mapPoints = React.useMemo(
    () => [
      ...points.filter((p) => p.id !== item.id),
      ...(point ? [point] : []),
    ],
    [points, point?.lat, point?.lon, point?.area, item.id],
  );
  const run = async (action: () => Promise<void>, closeOnSuccess = true, complete?: () => void) => {
    if (running.current || closed.current) return;
    running.current = true;
    setBusy(true);
    setError(undefined);
    setSuccess(undefined);
    try {
      await action();
      if (mounted.current && !closed.current) complete?.();
      if (closeOnSuccess && mounted.current && !closed.current) close();
    } catch (caught) {
      if (!mounted.current || closed.current) return;
      setError(
        caught instanceof Error
          ? caught.message
          : "Your changes could not be saved.",
      );
    } finally {
      running.current = false;
      if (mounted.current && !closed.current) setBusy(false);
    }
  };
  const open = async (value?: string) => {
    const url = safeWebUrl(value);
    if (!url) return;
    try {
      await Linking.openURL(url);
    } catch {
      if (mounted.current && !closed.current) setError("This link could not be opened.");
    }
  };
  const saved = /^\d+$/.test(item.id),
    processingState = dreamProcessingState(item),
    processing = processingState?.kind === "sorting" || (processingState?.kind === "upload" && item.uploadStatus !== "failed");
  const canRetry = !processing && (item.status === "failed" || item.needsReview || item.uploadStatus === "failed" || processingState?.kind === "unreadable" || processingState?.kind === "failed");
  const locationLine = [...new Set([item.regionOrNeighborhood, item.city, item.country].filter(Boolean))].join(" · ");
  const sourceDescription = item.summary.trim() || item.caption?.trim() || "";
  const cleanedDescription = sourceDescription.replace(/https?:\/\/\S+/gi, "").replace(/(^|\s)#[\p{L}\p{N}_]+/gu, " ").replace(/\s+/g, " ").trim();
  const description = sourceTitle && cleanedDescription === displayName ? "" : sourceDescription;
  const beginEditing = () => {
    setMenuOpen(false);
    setName(item.placeName || ""); setCity(item.city || "");
    setCountry(item.country || ""); setRegion(item.regionOrNeighborhood || "");
    setSummary(item.summary); setTags(item.tags.join(", ")); setCategory(item.category);
    mapsBaseline.current = item.googleMapsUrl || "";
    draftBaseline.current = draftFingerprint(draftFromItem(item));
    setMaps(mapsBaseline.current);
    setSuccess(undefined);
    setEditing(true);
  };
  const savedFeedback = (message: string) => {
    setSuccess(message);
    void selectionHaptic("confirmation");
  };
  return (
    <Modal
      visible={visible}
      transparent
      animationType={reducedMotion ? "none" : "fade"}
      presentationStyle="overFullScreen"
      onRequestClose={requestClose}
    >
      <KeyboardAvoidingView
        style={[s.overlay, { paddingTop: Math.max(insets.top + 12, 24), paddingBottom: Math.max(insets.bottom, 12) }]}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Pressable accessibilityLabel="Dismiss place details" accessibilityRole="button" onPress={requestClose} style={s.backdrop} />
        <View style={[s.screen, { maxHeight: height * .91 }]} accessibilityViewIsModal>
          <View style={s.toolbar}>
            <Text style={s.sheetLabel}>{editing ? "Edit place" : "Saved place"}</Text>
            {!editing && !discarding && !confirmDelete && !processing && <Pressable
              accessibilityLabel="More place options"
              accessibilityRole="button"
              accessibilityState={{ expanded: menuOpen }}
              onPress={() => setMenuOpen(!menuOpen)}
              style={s.icon}
            ><Text style={s.moreIcon}>•••</Text></Pressable>}
            <Pressable
              accessibilityLabel="Close place"
              accessibilityRole="button"
              onPress={requestClose}
              style={s.icon}
            >
              <WWIcon name="close" />
            </Pressable>
          </View>
        {discarding ? <View style={s.discardPanel}>
          <Text accessibilityRole="header" style={s.candidateName}>Discard changes?</Text>
          <Text style={s.locationHint}>Your saved place will stay as it was.</Text>
          <View style={s.actions}>
            <WWButton label="Keep editing" onPress={() => setDiscarding(false)} />
            <WWButton label="Discard changes" secondary onPress={close} />
          </View>
        </View> : confirmDelete ? <View style={s.discardPanel}>
          <Text accessibilityRole="header" style={s.candidateName}>Remove saved place?</Text>
          <Text style={s.locationHint}>This removes the place from your collection. Other places from the reel will stay saved.</Text>
          <View style={s.actions}>
            <WWButton label="Keep place" secondary disabled={busy} onPress={() => setConfirmDelete(false)} />
            <WWButton label={busy ? "Removing…" : "Remove"} disabled={busy} onPress={() => void run(() => onDelete(item.id))} />
          </View>
          {error && <Text accessibilityRole="alert" style={s.error}>{error}</Text>}
        </View> : <ScrollView
          keyboardShouldPersistTaps="handled"
          importantForAccessibility={menuOpen ? "no-hide-descendants" : "auto"}
          contentContainerStyle={{
            paddingHorizontal: 20,
            paddingBottom: 24,
          }}
        >
          {busy ? <Text accessibilityLiveRegion="polite" style={s.review}>This request can finish after you close this view.</Text> : null}
          {success && <Text accessibilityLiveRegion="polite" style={s.success}>{success}</Text>}
          {!editing ? (
            <>
              <View style={s.photo}>
                <DreamPhoto item={item} />
              </View>
              <Text accessibilityRole="header" numberOfLines={sourceTitle ? 3 : undefined} style={[s.title, { fontSize: titleSize, lineHeight: titleSize * 39 / 34 }]}>
                {displayName}
              </Text>
              <Text style={s.location}>{dreamLocationType(locationItem)}{locationLine ? ` · ${locationLine}` : ""}</Text>
              {description ? <>
                <Text style={s.summary}>{!expandedSummary && description.length > 220 ? `${description.slice(0, 220).replace(/\s+\S*$/, "")}…` : description}</Text>
                {description.length > 220 && <Pressable
                  accessibilityRole="button" accessibilityState={{ expanded: expandedSummary }}
                  onPress={() => setExpandedSummary(!expandedSummary)} style={s.readMore}
                ><Text style={s.sourceText}>{expandedSummary ? "Read less" : "Read more"}</Text></Pressable>}
              </> : null}
              {sourceCount > 1 && onShowSource && <Pressable
                accessibilityRole="button"
                accessibilityLabel={`View ${sourceCount} places from this reel`}
                onPress={() => { if (closed.current) return; close(); onShowSource(); }}
                style={s.sourceLink}
              ><Text style={s.sourceText}>{sourceCount} places from this reel</Text><WWIcon name="chevron" size={14} color={colors.blue} /></Pressable>}
              {processingState && !processing && (
                <Text style={s.review}>
                  {processingState.detail}
                </Text>
              )}
              {processing && (
                <Text style={s.review}>
                    {item.uploadStatus
                    ? 'Reel saved on this device.'
                    : processingState?.detail}
                </Text>
              )}
              {saved && !processing && (
                <View style={s.locationPanel}>
                  <View style={s.locationHeading}>
                    <WWIcon name="pin" size={17} />
                    <Text style={s.locationLabel}>{locationItem.coordinatePrecision === "area" ? "Area on map" : "Location"}</Text>
                  </View>
                  {liveLocation.loading && <Text accessibilityLiveRegion="polite" style={s.locationHint}>{shownPoint && locationItem.coordinatePrecision !== "area" ? "Loading address…" : "Loading location details…"}</Text>}
                  {liveLocation.error && <View>
                    <Text accessibilityRole="alert" style={s.locationHint}>{liveLocation.error}</Text>
                  </View>}
                  {locationItem.coordinatePrecision === "area" && shownPoint && <Text style={s.locationHint}>The marker shows the general area.</Text>}
                  {locationItem.coordinatePrecision !== "area" && locationItem.locationAddress && <Text selectable style={s.locationAddress}>{locationItem.locationAddress}</Text>}
                  {shownPoint ? <DreamPlacesMap points={[shownPoint]} fitKey={`location-${item.id}`} height={248} /> : !liveLocation.loading && !liveLocation.error ? (
                    <>
                      <Text accessibilityLiveRegion="polite" style={s.locationHint}>{locationExplanation(locationItem)}</Text>
                    </>
                  ) : null}
                  {locationItem.locationProvider === "google_places" && Boolean(locationItem.locationAddress || liveLocation.details?.locationAttributions.length) &&
                    <GoogleAttribution values={liveLocation.details?.locationAttributions ?? []} onOpen={open} />}
                  {item.locationProvider === "geoapify" && !point && (item.locationCandidates?.length ?? 0) > 0 &&
                    <View style={s.attributionLinks}>
                      <Pressable accessibilityRole="link" style={s.attribution} onPress={() => void open("https://www.geoapify.com/")}>
                        <Text style={s.attributionText}>Geoapify</Text>
                      </Pressable>
                      <Pressable accessibilityRole="link" style={s.attribution} onPress={() => void open("https://www.openstreetmap.org/copyright")}>
                        <Text style={s.attributionText}>© OpenStreetMap</Text>
                      </Pressable>
                    </View>}
                </View>
              )}
              <View style={[s.primaryActions, fontScale > 1.3 && s.actionsStack]}>
                <View style={s.primaryAction}>
                <WWButton
                  label="View reel"
                  secondary
                  onPress={() => void open(item.sourceUrl)}
                />
                </View>
                {safeWebUrl(mapsUrl) && (
                  <View style={s.primaryAction}>
                  <WWButton
                    label="Open in Maps"
                    onPress={() => void open(mapsUrl)}
                  />
                  </View>
                )}
              </View>
            </>
          ) : (
            <>
              <Field disabled={busy} label="Place name" value={name} onChange={setName} />
              <View style={[s.fields, fontScale > 1.25 && s.actionsStack]}>
                <View style={s.fieldColumn}>
                  <Field disabled={busy} label="City" value={city} onChange={setCity} />
                </View>
                <View style={s.fieldColumn}>
                  <Field
                    disabled={busy}
                    label="Country"
                    value={country}
                    onChange={setCountry}
                  />
                </View>
              </View>
              <Field
                disabled={busy}
                label="Neighborhood / region"
                value={region}
                onChange={setRegion}
              />
              <Text style={s.label}>Category</Text>
              <View style={s.categories}>
                {categories.map((value) => (
                  <Pressable
                    accessibilityRole="radio"
                    disabled={busy}
                    accessibilityState={{ checked: category === value, disabled: busy }}
                    key={value}
                    onPress={() => setCategory(value)}
                    style={[
                      s.categoryPill,
                      category === value && s.categorySelected,
                    ]}
                  >
                    <Text
                      style={[
                        s.categoryText,
                        category === value && { color: colors.paper },
                      ]}
                    >
                      {categoryLabel(value)}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Field
                disabled={busy}
                label="Notes"
                value={summary}
                onChange={setSummary}
                multiline
              />
              <Field
                disabled={busy}
                label="Tags, separated by commas"
                value={tags}
                onChange={setTags}
              />
              <Field disabled={busy} label="Maps link" value={maps} onChange={setMaps} url />
              <Pressable
                disabled={busy}
                onPress={() => setPlacing(!placing)}
                style={s.pinAction}
              >
                <WWIcon name="pin" size={19} />
                <Text style={s.pinText}>
                  {placing
                    ? "Finish placing pin"
                    : point
                      ? "Adjust pin on map"
                      : "Place a pin on the map"}
                </Text>
              </Pressable>
              {placing && (
                <>
                  <Text style={s.mapHint}>
                    Move the map to the place, then tap its location. Save
                    changes to keep the pin.
                  </Text>
                  <DreamPlacesMap
                    points={mapPoints}
                    overview={overview}
                    fitKey={`edit-${item.id}`}
                    selectedId={point?.id}
                    placing
                    onPlace={(lat, lon) =>
                      !busy && setMaps(
                        `https://www.google.com/maps/search/?api=1&query=${lat.toFixed(6)},${lon.toFixed(6)}`,
                      )
                    }
                    height={245}
                  />
                </>
              )}
              <View style={s.save}>
                <WWButton
                  label={busy ? "Saving…" : "Save changes"}
                  disabled={busy || !name.trim() || !country.trim()}
                  onPress={() => {
                    if (maps.trim() && !safeWebUrl(maps)) {
                      setError("Use a complete https:// Maps link.");
                      return;
                    }
                    void run(() =>
                      onSave(item.id, {
                        placeName: name.trim(),
                        city: city.trim() || undefined,
                        country: country.trim(),
                        regionOrNeighborhood: region.trim() || undefined,
                        summary: summary.trim(),
                        tags: tags
                          .split(",")
                          .map((t) => t.trim())
                          .filter(Boolean),
                        category,
                        ...(maps.trim() !== mapsBaseline.current.trim() ? { googleMapsUrl: maps.trim() || undefined } : {}),
                        needsReview: false,
                      }), false, () => {
                        draftBaseline.current = currentDraft;
                        setEditing(false); setPlacing(false);
                        savedFeedback("Changes saved.");
                      },
                    );
                  }}
                />
              </View>
            </>
          )}
          {error && (
            <Text accessibilityRole="alert" style={s.error}>
              {error}
            </Text>
          )}
        </ScrollView>}
        {menuOpen && !editing && <View style={s.menuLayer} accessibilityViewIsModal>
          <Pressable accessibilityLabel="Dismiss place options" accessibilityRole="button" onPress={() => setMenuOpen(false)} style={StyleSheet.absoluteFill} />
          <View style={s.menu}>
            {saved && <MenuAction label="Edit details" disabled={busy} onPress={beginEditing} />}
            {liveLocation.error && <MenuAction label="Retry details" disabled={busy} onPress={() => { setMenuOpen(false); liveLocation.retry(); }} />}
            {onLocate && canFindLocation(locationItem) && <MenuAction label="Retry location" disabled={busy} onPress={() => {
              setMenuOpen(false); void run(() => onLocate(item.id), false);
            }} />}
            {canRetry && <MenuAction label={saved ? "Retry reading post" : "Retry save"} disabled={busy} onPress={() => {
              setMenuOpen(false); onRetry(); close();
            }} />}
            {!processing && <MenuAction label="Remove saved place" destructive disabled={busy} onPress={() => {
              setMenuOpen(false); setConfirmDelete(true);
            }} />}
          </View>
        </View>}
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function MenuAction({ label, onPress, disabled, destructive = false }: {
  label: string; onPress: () => void; disabled?: boolean; destructive?: boolean;
}) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled: Boolean(disabled) }}
    disabled={disabled} onPress={onPress} style={s.menuAction}>
    <Text style={[s.menuText, destructive && s.menuDestructive, disabled && s.menuDisabled]}>{label}</Text>
  </Pressable>;
}

function GoogleAttribution({ values, onOpen }: { values: { displayName: string; uri?: string }[]; onOpen: (url?: string) => Promise<void> }) {
  return <View style={s.googleAttribution}>
    <Text style={s.googleName}>Google Maps</Text>
    {values.map((value, index) => safeWebUrl(value.uri)
      ? <Pressable key={`${value.displayName}-${index}`} accessibilityRole="link" style={s.attribution} onPress={() => void onOpen(value.uri)}><Text style={s.attributionText}>{value.displayName}</Text></Pressable>
      : <Text key={`${value.displayName}-${index}`} style={s.attributionText}>{value.displayName}</Text>)}
  </View>;
}
function Field({
  label,
  value,
  onChange,
  multiline = false,
  url = false,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  multiline?: boolean;
  url?: boolean;
  disabled?: boolean;
}) {
  return (
    <View style={s.field}>
      <Text style={s.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        editable={!disabled}
        onChangeText={onChange}
        multiline={multiline}
        autoCapitalize={url ? "none" : "sentences"}
        autoCorrect={!url}
        keyboardType={url ? "url" : "default"}
        style={[s.input, multiline && s.multiline]}
      />
    </View>
  );
}
const s = StyleSheet.create({
  discardPanel: { padding: 24, gap: 12 },
  success: { paddingVertical: 12, marginBottom: 12, fontFamily: fonts.sansSemi, fontSize: 13, lineHeight: 20, color: colors.blue },
  googleAttribution: { paddingTop: 10, paddingBottom: 5, gap: 4, alignItems: "flex-start" },
  googleName: { color: "#5e5e5e", fontFamily: fonts.sansRegular, fontSize: 12 },
  locationPanel: { marginTop: 22, paddingTop: 16, paddingBottom: 4, borderTopWidth: 1, borderColor: colors.paperBorder, gap: 10 },
  locationHeading: { flexDirection: "row", alignItems: "center", gap: 8 },
  locationLabel: { fontFamily: fonts.sans, fontSize: 14, color: colors.ink },
  locationAddress: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.ink },
  locationHint: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk },
  candidateName: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  attribution: { minHeight: 44, justifyContent: "center" },
  attributionLinks: { flexDirection: "row", flexWrap: "wrap", gap: 16 },
  attributionText: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  overlay: { flex: 1, justifyContent: "flex-end", alignItems: "center", paddingHorizontal: 12 },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(20, 39, 45, .38)" },
  screen: {
    flex: 1, width: "100%", maxWidth: 560, backgroundColor: colors.paperSoft,
    borderRadius: 12, overflow: "hidden", borderWidth: 1, borderColor: colors.paperBorder,
  },
  toolbar: { flexDirection: "row", alignItems: "center", paddingLeft: 20, paddingRight: 8, minHeight: 60 },
  sheetLabel: { flex: 1, fontFamily: fonts.sansSemi, color: colors.mutedInk, fontSize: 12 },
  moreIcon: { color: colors.ink, fontSize: 16, letterSpacing: 2, lineHeight: 24 },
  menuLayer: { ...StyleSheet.absoluteFillObject, zIndex: 20 },
  menu: { position: "absolute", top: 54, right: 12, width: "82%", maxWidth: 265,
    backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.paperBorder,
    borderRadius: 8, paddingVertical: 5, elevation: 6,
    shadowColor: colors.ink, shadowOpacity: .12, shadowOffset: { width: 0, height: 4 }, shadowRadius: 12 },
  menuAction: { minHeight: 48, paddingHorizontal: 17, paddingVertical: 13, justifyContent: "center" },
  menuText: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 20, color: colors.ink },
  menuDestructive: { color: colors.red },
  menuDisabled: { opacity: .45 },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  photo: {
    aspectRatio: 1.55,
    padding: 5,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  title: {
    fontFamily: fonts.display,
    fontSize: 34,
    lineHeight: 39,
    color: colors.blue,
    marginTop: 19,
  },
  location: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.mutedInk,
    marginTop: 7,
  },
  summary: {
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    lineHeight: 23,
    color: colors.ink,
    marginTop: 16,
  },
  sourceLink: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingVertical: 8, marginTop: 4 },
  readMore: { alignSelf: "flex-start", minHeight: 44, justifyContent: "center" },
  sourceText: { fontFamily: fonts.sansSemi, fontSize: 12, lineHeight: 19, color: colors.blue },
  review: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.ink,
    marginTop: 16,
  },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 17 },
  primaryActions: { flexDirection: "row", gap: 10, marginTop: 22, alignItems: "stretch" },
  primaryAction: { flex: 1 },
  actionsStack: { flexDirection: "column", alignItems: "stretch" },
  fields: { flexDirection: "row", gap: 12 },
  fieldColumn: { flex: 1 },
  field: { marginBottom: 16 },
  label: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    color: colors.ink,
    marginBottom: 7,
  },
  input: {
    minHeight: 47,
    paddingHorizontal: 12,
    paddingVertical: 11,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 3,
    backgroundColor: colors.paper,
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.ink,
  },
  multiline: { minHeight: 105, textAlignVertical: "top" },
  categories: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 7,
    marginBottom: 19,
  },
  categoryPill: {
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderColor: colors.paperBorder,
    borderWidth: 1,
    borderRadius: 3,
  },
  categorySelected: { backgroundColor: colors.blue, borderColor: colors.blue },
  categoryText: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    color: colors.ink,
  },
  pinAction: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    minHeight: 46,
  },
  pinText: { fontFamily: fonts.sansSemi, fontSize: 13, color: colors.blue },
  mapHint: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.mutedInk,
    marginBottom: 12,
  },
  save: { marginTop: 22 },
  error: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.red,
    marginTop: 16,
  },
});
