import React from "react";
import {
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
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
import { WWButton, WWHeader, WWIcon } from "../WorldWindowUI";
import { fitDisplayFont } from "../displayTextFit";
import { getMobileVisualWidth } from "../../../utils/mobileLayout";
import { PaperMap } from "../trips/PaperMap";
import type { MapPoint } from "../trips/tripPresentation";
import { categoryLabel, exactMapPoint, safeWebUrl } from "./dreamPresentation";
import { DreamPhoto } from "./DreamPhoto";
import { isFindingLocation, locationExplanation } from "./locationPresentation";

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
  onConfirmLocation,
}: {
  item: DreamItem;
  points: MapPoint[];
  onClose: () => void;
  onSave: (id: string, patch: Partial<DreamItem>) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onRetry: () => void;
  onLocate?: (id: string) => Promise<void>;
  onConfirmLocation?: (id: string, candidateId: string) => Promise<void>;
}) {
  const insets = useSafeAreaInsets();
  const { width, fontScale } = useWindowDimensions();
  const displayName = item.placeName || item.city || "Saved inspiration";
  const titleSize = fitDisplayFont(displayName, 34, getMobileVisualWidth(width) - 48, fontScale);
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
  const [editing, setEditing] = React.useState(false),
    [confirmDelete, setConfirmDelete] = React.useState(false),
    [busy, setBusy] = React.useState(false),
    [error, setError] = React.useState<string>(),
    [placing, setPlacing] = React.useState(false);
  const [name, setName] = React.useState(item.placeName || ""),
    [city, setCity] = React.useState(item.city || ""),
    [country, setCountry] = React.useState(item.country || ""),
    [region, setRegion] = React.useState(item.regionOrNeighborhood || ""),
    [summary, setSummary] = React.useState(item.summary),
    [tags, setTags] = React.useState(item.tags.join(", ")),
    [maps, setMaps] = React.useState(item.googleMapsUrl || ""),
    [category, setCategory] = React.useState(item.category);
  const mapsBaseline = React.useRef(item.googleMapsUrl || "");
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
      ? { latitude: undefined, longitude: undefined }
      : {}),
  });
  const mapPoints = React.useMemo(
    () => [
      ...points.filter((p) => p.id !== item.id),
      ...(point ? [point] : []),
    ],
    [points, point?.lat, point?.lon, item.id],
  );
  const run = async (action: () => Promise<void>, closeOnSuccess = true) => {
    if (running.current || closed.current) return;
    running.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await action();
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
    processing = item.status === "processing" || item.status === "created";
  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={close}
    >
      <KeyboardAvoidingView
        style={[s.screen, { paddingTop: insets.top }]}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <WWHeader
          title={editing ? "Edit place" : "Saved place"}
          action={
            <Pressable
              accessibilityLabel="Close place"
              accessibilityRole="button"
              onPress={close}
              style={s.icon}
            >
              <WWIcon name="close" />
            </Pressable>
          }
        />
        <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{
            paddingHorizontal: 24,
            paddingBottom: insets.bottom + 32,
          }}
        >
          {busy ? <Text accessibilityLiveRegion="polite" style={s.review}>This request can finish after you close this view.</Text> : null}
          {!editing ? (
            <>
              <View style={s.photo}>
                <DreamPhoto item={item} />
              </View>
              <Text style={s.category}>{categoryLabel(item.category)}</Text>
              <Text style={[s.title, { fontSize: titleSize, lineHeight: titleSize * 39 / 34 }]}>
                {displayName}
              </Text>
              <Text style={s.location}>
                {[item.regionOrNeighborhood, item.city, item.country]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
              <Text style={s.summary}>{item.summary}</Text>
              {item.tags.length > 0 && (
                <Text style={s.tags}>{item.tags.join(" · ")}</Text>
              )}
              {item.needsReview && (
                <Text style={s.review}>
                  Check the place and location before confirming this save.
                </Text>
              )}
              {processing && (
                <Text style={s.review}>
                  Reading this post. Its original link is saved.
                </Text>
              )}
              {saved && !processing && (
                <View style={s.locationPanel}>
                  <View style={s.locationHeading}>
                    <WWIcon name="pin" size={17} />
                    <Text style={s.locationLabel}>Location</Text>
                  </View>
                  {item.locationAddress && <Text selectable style={s.locationAddress}>{item.locationAddress}</Text>}
                  {point ? <PaperMap points={[point]} fitKey={`location-${item.id}`} height={170} /> : (
                    <>
                      <Text accessibilityLiveRegion="polite" style={s.locationHint}>{locationExplanation(item)}</Text>
                      {(item.locationCandidates ?? []).map(candidate => (
                        <View key={candidate.id} style={s.candidate}>
                          <Text style={s.candidateName}>{candidate.name}</Text>
                          <Text selectable style={s.locationHint}>{candidate.address}</Text>
                          <View style={[s.actions, fontScale > 1.25 && s.actionsStack]}>
                            {onConfirmLocation && <WWButton label="Use this location" disabled={busy}
                              onPress={() => void run(() => onConfirmLocation(item.id, candidate.id))} />}
                            {safeWebUrl(candidate.googleMapsUrl) && <WWButton label="View map ↗" secondary
                              onPress={() => void open(candidate.googleMapsUrl)} />}
                          </View>
                        </View>
                      ))}
                      {onLocate && !isFindingLocation(item) && Boolean(item.placeName) && item.locationStatus !== "needs_review" &&
                        <View style={s.actions}><WWButton
                          label={item.locationStatus === "failed" || item.locationStatus === "not_found" || item.locationStatus === "blocked" ? "Retry location" : "Find location"}
                          secondary disabled={busy} onPress={() => void run(() => onLocate(item.id), false)} /></View>}
                    </>
                  )}
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
              <View style={s.actions}>
                <WWButton
                  label="Original post"
                  secondary
                  onPress={() => void open(item.sourceUrl)}
                />
                {safeWebUrl(item.googleMapsUrl) && (
                  <WWButton
                    label="Maps"
                    secondary
                    onPress={() => void open(item.googleMapsUrl)}
                  />
                )}
              </View>
              {!processing && (
                <View style={s.actions}>
                  {saved && (
                    <WWButton
                      label="Edit details"
                      secondary
                      disabled={busy}
                      onPress={() => {
                        setName(item.placeName || ""); setCity(item.city || "");
                        setCountry(item.country || ""); setRegion(item.regionOrNeighborhood || "");
                        setSummary(item.summary); setTags(item.tags.join(", ")); setCategory(item.category);
                        mapsBaseline.current = item.googleMapsUrl || "";
                        setMaps(mapsBaseline.current);
                        setEditing(true);
                      }}
                    />
                  )}
                  {item.needsReview && saved && (
                    <WWButton
                      label={busy ? "Saving…" : "Confirm place"}
                      disabled={busy}
                      onPress={() =>
                        void run(() => onSave(item.id, { needsReview: false }))
                      }
                    />
                  )}
                  {item.status === "failed" && (
                    <WWButton
                      label="Retry save"
                      onPress={() => {
                        onRetry();
                        close();
                      }}
                    />
                  )}
                </View>
              )}
            </>
          ) : (
            <>
              <Field disabled={busy} label="Place name" value={name} onChange={setName} />
              <View style={s.fields}>
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
                  <PaperMap
                    points={mapPoints}
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
                      }),
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
          {!processing && !confirmDelete ? (
            <Pressable
              disabled={busy}
              onPress={() => setConfirmDelete(true)}
              style={s.delete}
            >
              <Text style={s.deleteText}>Remove saved place</Text>
            </Pressable>
          ) : confirmDelete ? (
            <View style={s.deleteConfirm}>
              <Text style={s.review}>
                Remove this place from your saved collection?
              </Text>
              <View style={s.actions}>
                <WWButton
                  label="Keep place"
                  secondary
                  disabled={busy}
                  onPress={() => setConfirmDelete(false)}
                />
                <WWButton
                  label={busy ? "Removing…" : "Remove"}
                  disabled={busy}
                  onPress={() => void run(() => onDelete(item.id))}
                />
              </View>
            </View>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
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
  locationPanel: { marginTop: 22, paddingTop: 16, paddingBottom: 4, borderTopWidth: 1, borderColor: colors.paperBorder, gap: 10 },
  locationHeading: { flexDirection: "row", alignItems: "center", gap: 8 },
  locationLabel: { fontFamily: fonts.sans, fontSize: 14, color: colors.ink },
  locationAddress: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.ink },
  locationHint: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk },
  candidate: { borderTopWidth: 1, borderColor: colors.paperBorder, paddingVertical: 14, gap: 5 },
  candidateName: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  attribution: { minHeight: 44, justifyContent: "center" },
  attributionLinks: { flexDirection: "row", flexWrap: "wrap", gap: 16 },
  attributionText: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  photo: {
    height: 225,
    padding: 6,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  category: {
    fontFamily: fonts.mono,
    fontSize: 10,
    letterSpacing: 1,
    color: colors.red,
    marginTop: 22,
  },
  title: {
    fontFamily: fonts.display,
    fontSize: 34,
    lineHeight: 39,
    color: colors.blue,
    marginTop: 8,
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
    marginTop: 19,
  },
  tags: {
    fontFamily: fonts.mono,
    fontSize: 10,
    lineHeight: 17,
    color: colors.mutedInk,
    marginTop: 15,
  },
  review: {
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 20,
    color: colors.ink,
    marginTop: 16,
  },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 17 },
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
  delete: { minHeight: 48, justifyContent: "center", marginTop: 20 },
  deleteText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.red,
  },
  deleteConfirm: {
    marginTop: 18,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
  },
});
