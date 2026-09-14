import React from "react";
import {
  Animated,
  BackHandler,
  FlatList,
  KeyboardAvoidingView,
  Keyboard,
  Linking,
  Modal,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { fitDisplayFont } from "../components/world-window/displayTextFit";
import { getMobileVisualWidth } from "../utils/mobileLayout";
import { BottomNav } from "../components/trotter/TrotterKit";
import {
  WWButton,
  WWEmpty,
  WWHeader,
  WWIcon,
} from "../components/world-window/WorldWindowUI";
import { CountryPostcard } from "../components/world-window/dreams/CountryPostcard";
import { DreamEditor } from "../components/world-window/dreams/DreamEditor";
import {
  DreamPhoto,
  PlaceSymbol,
} from "../components/world-window/dreams/DreamPhoto";
import {
  categoryLabel,
  cityNames,
  countryBoards,
  countryKey,
  dreamCategories,
  DreamFilter,
  exactMapPoint,
  filterDreams,
  safeWebUrl,
} from "../components/world-window/dreams/dreamPresentation";
import { countryRegion } from "../components/world-window/dreams/countryRegion";
import { dreamCopy } from "../components/world-window/dreams/dreamCopy";
import { canFindLocation, isFindingLocation, locationNote } from "../components/world-window/dreams/locationPresentation";
import { DreamPlacesMap } from "../components/world-window/dreams/DreamPlacesMap";
import type { MapPoint } from "../components/world-window/trips/tripPresentation";
import type { BottomNavTab } from "../data/trotterMock";
import { DreamItem, useDreams } from "../services/dreams";
import { colors, fonts, layout } from "../theme/trotterTheme";
import { paperEase, PressFeedback as Pressable, useReducedMotion } from "../components/world-window/motion";

export function DreamsScreen({
  active,
  onChange,
  visible = true,
  onBackHandlerChange,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  visible?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
}) {
  const insets = useSafeAreaInsets(),
    store = useDreams();
  const reducedMotion = useReducedMotion();
  const [country, setCountry] = React.useState<{
      key: string;
      title: string;
    }>(),
    [review, setReview] = React.useState(false),
    [capture, setCapture] = React.useState(false),
    [selectedMode, setSelectedMode] = React.useState<"view" | "edit">("view"),
    [returningCountry, setReturningCountry] = React.useState<string>(),
    [selectedId, setSelectedId] = React.useState<string>();
  const editorBack = React.useRef<(() => void) | null>(null),
    captureBack = React.useRef<(() => void) | null>(null),
    countryBack = React.useRef<(() => void) | null>(null);
  const registerEditorBack = React.useCallback((handler: (() => void) | null) => { editorBack.current = handler; }, []);
  const registerCountryBack = React.useCallback((handler: (() => void) | null) => { countryBack.current = handler; }, []);
  const registerCaptureBack = React.useCallback((handler: (() => void) | null) => { captureBack.current = handler; }, []);
  const homeOffset = React.useRef(0),
    selected = store.items.find((item) => item.id === selectedId);
  const boards = React.useMemo(() => countryBoards(store.items), [store.items]);
  const pointsByCountry = React.useMemo(() => {
    const grouped = new Map<string, MapPoint[]>();
    for (const item of store.items) {
      const point = exactMapPoint(item);
      if (!point) continue;
      const key = countryKey(item.country);
      const entries = grouped.get(key) ?? [];
      entries.push(point);
      grouped.set(key, entries);
    }
    return grouped;
  }, [store.items]);
  const countryItems = React.useMemo(
    () =>
      store.items.filter((item) => countryKey(item.country) === country?.key),
    [store.items, country?.key],
  );
  const reviews = React.useMemo(
    () =>
      store.items.filter(
        (item) => item.needsReview || item.status === "failed" || item.locationStatus === "needs_review",
      ),
    [store.items],
  );
  const back = () => {
    setReturningCountry(country?.key);
    setCountry(undefined);
    setReview(false);
  };
  React.useEffect(() => {
    const goBack = () => {
      if (!visible) return false;
      if (capture && captureBack.current) { captureBack.current(); return true; }
      if (selected && editorBack.current) { editorBack.current(); return true; }
      if (!country && !review) return false;
      if (countryBack.current) countryBack.current(); else back();
      return true;
    };
    onBackHandlerChange?.(visible ? goBack : null);
    const handler = !onBackHandlerChange && visible
      ? BackHandler.addEventListener("hardwareBackPress", goBack) : undefined;
    return () => { handler?.remove(); onBackHandlerChange?.(null); };
  }, [country, review, visible, selected, capture, onBackHandlerChange]);
  const loading = store.status === "loading" || store.status === "refreshing";
  const actions = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Save an Instagram place"
      onPress={() => setCapture(true)}
      style={s.icon}
    >
      <WWIcon name="plus" size={23} />
    </Pressable>
  );
  return (
    <View style={[s.screen, { paddingTop: insets.top }]}>
      {country || review ? (
        <CountryPlaces
          key={country?.key || "review"}
          title={review ? "To review" : country?.title || "Saved places"}
          items={review ? reviews : countryItems}
          review={review}
          topInset={0}
          bottomInset={insets.bottom}
          loading={loading}
          error={store.error}
          onBack={back}
          motion={!reducedMotion}
          active={visible}
          onBackRequestChange={registerCountryBack}
          onRefresh={() => void store.refresh()}
          onSelect={(id, mode = "view") => { setSelectedMode(mode); setSelectedId(id); }}
          onLocateMissing={store.locateMissing}
        />
      ) : (
        <FlatList
          data={boards}
          keyExtractor={(board) => board.key}
          contentOffset={{ x: 0, y: homeOffset.current }}
          onScroll={(event) => {
            homeOffset.current = event.nativeEvent.contentOffset.y;
          }}
          scrollEventThrottle={100}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{
            paddingBottom: insets.bottom + layout.bottomNavHeight + 24,
          }}
          refreshControl={
            <RefreshControl
              refreshing={loading}
              onRefresh={() => void store.refresh()}
              tintColor={colors.blue}
            />
          }
          initialNumToRender={4}
          windowSize={5}
          ListHeaderComponent={
            <>
              <WWHeader title="Dreams" action={actions} />
              {reviews.length > 0 && (
                <View style={s.homeMeta}>
                  {reviews.length > 0 && (
                    <Pressable
                      onPress={() => setReview(true)}
                      accessibilityRole="button"
                      style={s.reviewButton}
                    >
                      <Text style={s.reviewText}>Review {reviews.length}</Text>
                      <WWIcon name="chevron" size={13} color={colors.red} />
                    </Pressable>
                  )}
                </View>
              )}
              {store.processingItems.length > 0 && (
                <View style={s.notice}>
                  <Text style={s.noticeText}>
                    Reading {store.processingItems.length}{" "}
                    {store.processingItems.length === 1
                      ? "shared post"
                      : "shared posts"}
                    …
                  </Text>
                </View>
              )}
              {store.error && (
                <ErrorLine
                  error={store.error}
                  onRetry={() => void store.refresh()}
                />
              )}
            </>
          }
          renderItem={({ item }) => (
            <CountryPostcard
              board={item}
              returning={returningCountry === item.key}
              visible={visible}
              onReturned={() => setReturningCountry(undefined)}
              onPress={() => { setReturningCountry(undefined); setCountry({ key: item.key, title: item.title }); }}
            />
          )}
          ListEmptyComponent={
            <WWEmpty
              title={
                loading ? "Loading your saved places…" : "Your next places"
              }
              body={
                loading
                  ? undefined
                  : "Share an Instagram post to Trotter, or paste its link here. Your saves come together by country."
              }
              action={
                !loading ? (
                  <WWButton
                    label="Save a place"
                    onPress={() => setCapture(true)}
                  />
                ) : undefined
              }
            />
          }
        />
      )}
      <BottomNav active={active} onChange={onChange} />
      {selected && (
        <DreamEditor
          key={selected.id}
          visible={visible}
          initialMode={selectedMode}
          onCloseRequestChange={registerEditorBack}
          item={selected}
          points={pointsByCountry.get(countryKey(selected.country)) ?? []}
          onClose={() => setSelectedId(undefined)}
          onSave={store.updateItem}
          onDelete={store.deleteItem}
          onLocate={store.locateItem}
          onConfirmLocation={store.confirmLocation}
          onRetry={() =>
            store.shareInstagramLink(selected.sourceUrl, selected.caption)
          }
        />
      )}
      {capture && (
        <CapturePlace
          visible={visible}
          onCloseRequestChange={registerCaptureBack}
          onClose={() => setCapture(false)}
          onSave={(url, caption) =>
            Boolean(store.shareInstagramLink(url, caption))
          }
        />
      )}
    </View>
  );
}

function CountryPlaces({
  title, items, review, topInset, bottomInset, loading, error, onBack, onRefresh,
  onSelect, onLocateMissing, motion, active = true, onBackRequestChange,
}: {
  title: string; items: DreamItem[]; review: boolean; topInset: number;
  bottomInset: number; loading: boolean; error?: string; onBack: () => void;
  onRefresh: () => void; onSelect: (id: string, mode?: "view" | "edit") => void;
  onLocateMissing: (ids: string[]) => Promise<void>; motion: boolean;
  active?: boolean;
  onBackRequestChange?: (handler: (() => void) | null) => void;
}) {
  const { width, fontScale } = useWindowDimensions();
  const countrySize = fitDisplayFont(title, 35, getMobileVisualWidth(width) - 152, fontScale, "italic");
  const [query, setQuery] = React.useState(""), [city, setCity] = React.useState(""),
    [category, setCategory] = React.useState<DreamFilter>("All"),
    [searching, setSearching] = React.useState(false),
    [opened, setOpened] = React.useState<string>(), [selected, setSelected] = React.useState<string>(),
    [queueing, setQueueing] = React.useState(false), [leaving, setLeaving] = React.useState(false);
  const queueLock = React.useRef(false), mounted = React.useRef(true), exitLock = React.useRef(false);
  const list = React.useRef<FlatList<DreamItem>>(null);
  const paper = React.useRef(new Animated.Value(motion ? 0 : 1)).current;
  const latestBack = React.useRef(onBack); latestBack.current = onBack;
  const isActive = React.useRef(active); isActive.current = active;
  const requestBack = React.useCallback(() => {
    if (exitLock.current) return;
    Keyboard.dismiss();
    exitLock.current = true; setLeaving(true);
    paper.stopAnimation();
    Animated.timing(paper, { toValue: 0, duration: motion ? 100 : 0, easing: paperEase, useNativeDriver: true })
      .start(({ finished }) => { if (finished && mounted.current && isActive.current) latestBack.current(); });
  }, [paper, motion]);
  React.useEffect(() => {
    mounted.current = true;
    Animated.timing(paper, { toValue: 1, duration: motion && !review ? 160 : 0, easing: paperEase, useNativeDriver: true }).start();
    return () => { mounted.current = false; paper.stopAnimation(); };
  }, []);
  React.useEffect(() => {
    if (!motion) {
      paper.stopAnimation(); paper.setValue(1);
      if (exitLock.current) latestBack.current();
    }
  }, [motion, paper]);
  React.useEffect(() => {
    if (!active) { paper.stopAnimation(); paper.setValue(1); exitLock.current = false; setLeaving(false); }
  }, [active, paper]);
  React.useEffect(() => {
    onBackRequestChange?.(requestBack);
    return () => onBackRequestChange?.(null);
  }, [requestBack, onBackRequestChange]);
  const region = React.useMemo(() => countryRegion(title), [title]);
  const cities = React.useMemo(() => cityNames(items), [items]);
  const visible = React.useMemo(() => filterDreams(items, query, city, category).sort((a, b) =>
    (a.city || "").localeCompare(b.city || "") || (a.placeName || "").localeCompare(b.placeName || "")),
    [items, query, city, category]);
  const points = React.useMemo(() => visible.map(exactMapPoint).filter((point): point is MapPoint => Boolean(point)), [visible]);
  const selectedPlace = visible.find(item => item.id === selected);
  const previewSize = fitDisplayFont(selectedPlace?.placeName || "Saved place", 21, getMobileVisualWidth(width) - 136, fontScale);
  const cityCounts = React.useMemo(() => {
    const counts = new Map<string | undefined, number>();
    for (const place of visible) counts.set(place.city, (counts.get(place.city) ?? 0) + 1);
    return counts;
  }, [visible]);
  const missing = React.useMemo(() => visible.filter(canFindLocation), [visible]);
  const finding = React.useMemo(() => visible.filter(isFindingLocation).length, [visible]);
  const findLocations = async () => {
    if (queueLock.current || !missing.length) return;
    queueLock.current = true; setQueueing(true);
    try { await onLocateMissing(missing.map(item => item.id)); }
    catch { /* Shared store preserves the save and exposes the retryable error. */ }
    finally { queueLock.current = false; if (mounted.current) setQueueing(false); }
  };
  React.useEffect(() => {
    if (city && !cities.includes(city)) setCity("");
    if (selected && !visible.some(item => item.id === selected)) setSelected(undefined);
    if (opened && !visible.some(item => item.id === opened)) setOpened(undefined);
  }, [city, cities, visible, selected, opened]);
  return (
    <View style={[s.countryScreen, { paddingTop: topInset }]} pointerEvents={leaving ? "none" : "auto"}>
      <Animated.View style={[s.countryHeader, { backfaceVisibility: "hidden", transform: [
        { perspective: 1000 }, { rotateY: paper.interpolate({ inputRange: [0, 1], outputRange: ["76deg", "0deg"] }) },
      ] }]}>
        <Pressable accessibilityRole="button" accessibilityLabel="Back to Dreams" onPress={requestBack} style={s.headerIcon}>
          <WWIcon name="back" size={22} />
        </Pressable>
        <View style={s.countryHeadingCopy}>
          <Text accessibilityRole="header" style={[s.countryTitle, { fontSize: countrySize, lineHeight: countrySize * 1.12 }]}>{title}</Text>
          <Text style={s.meta}>{items.length} saved {items.length === 1 ? "place" : "places"}</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={searching ? "Close search" : "Search saved places"}
          accessibilityState={{ expanded: searching }} style={s.headerIcon}
          onPress={() => { setSearching(!searching); setQuery(""); if (searching) Keyboard.dismiss(); }}>
          <WWIcon name={searching ? "close" : "search"} size={20} />
        </Pressable>
      </Animated.View>
      {searching && <TextInput autoFocus value={query} onChangeText={setQuery} placeholder="Search saved places"
        returnKeyType="search" onSubmitEditing={() => Keyboard.dismiss()}
        accessibilityLabel="Search saved places" placeholderTextColor={colors.mutedInk} style={s.search} />}
      <Animated.View style={[s.filterPanel, { opacity: paper }]}>
        {cities.length > 1 && <ScrollView horizontal showsHorizontalScrollIndicator={false}
          accessibilityLabel="Filter by city" contentContainerStyle={s.cityFilters}>
          {["", ...cities].map(value => <Pressable key={value || "all"} accessibilityRole="tab"
            accessibilityLabel={value ? `City: ${value}` : "All cities"} accessibilityState={{ selected: city === value }}
            onPress={() => setCity(value)} style={[s.city, city === value && s.cityActive]}>
            <Text style={[s.cityText, city === value && s.cityTextActive]}>{value || "All cities"}</Text>
          </Pressable>)}
        </ScrollView>}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityLabel="Filter by category"
          contentContainerStyle={s.categories}>
          {dreamCategories.filter(value => value === "All" || filterDreams(items, "", "", value).length > 0).map(value => {
            const count = filterDreams(items, query, city, value).length;
            return <Pressable key={value} accessibilityRole="tab" accessibilityLabel={`${value}, ${count} places`}
              accessibilityState={{ selected: category === value }} onPress={() => setCategory(value)}
              style={[s.category, category === value && s.categoryActive]}>
              <Text style={[s.categoryText, category === value && s.categoryTextActive]}>
                {value} <Text style={s.filterCount}>{count}</Text>
              </Text>
            </Pressable>;
          })}
        </ScrollView>
      </Animated.View>
      <Animated.View style={[s.countryContent, { opacity: paper, transform: [
        { translateY: paper.interpolate({ inputRange: [0, 1], outputRange: [motion ? 7 : 0, 0] }) },
      ] }]}>
        <FlatList ref={list} data={visible} keyExtractor={item => item.id}
          keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag" showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: bottomInset + layout.bottomNavHeight + 24 }}
          initialNumToRender={8} windowSize={7}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={onRefresh} tintColor={colors.blue} />}
          ListHeaderComponent={<>
            {!review && <View style={s.mapPaper}>
              <DreamPlacesMap overview={region} points={points} fitKey={`${title}-${city}-${category}-${query}`}
                height={248} selectedId={selected} onSelect={setSelected} />
              <View style={s.mapFoot}>
                <Text style={s.mapCount}>{points.length ? `${points.length} on map` : "No pinned places yet"}</Text>
                {points.length < visible.length && <Text style={s.mapNote}>
                  {visible.length - points.length} {visible.length - points.length === 1 ? "place needs" : "places need"} a pin
                </Text>}
              </View>
              {finding > 0 && <Text accessibilityLiveRegion="polite" style={s.findingNote}>
                Finding {finding === 1 ? "a location" : `${finding} locations`}… Pins appear here when ready.
              </Text>}
              {missing.length > 0 && <Pressable accessibilityRole="button" accessibilityLabel="Find locations"
                accessibilityState={{ disabled: queueing, busy: queueing }} disabled={queueing}
                style={s.mapSelection} onPress={() => void findLocations()}>
                <Text style={s.actionText}>{queueing ? "Starting lookup…" : "Find locations"}</Text><WWIcon name="pin" size={17} />
              </Pressable>}
              {selectedPlace && <Pressable accessibilityRole="button"
                accessibilityLabel={`Details for ${selectedPlace.placeName || "saved place"}`}
                style={s.mapPreview} onPress={() => onSelect(selectedPlace.id, "view")}>
                <View style={s.previewPhoto}><DreamPhoto item={selectedPlace} compact /></View>
                <View style={s.placeCopy}>
                  <Text style={s.placeType}>{categoryLabel(selectedPlace.category)}</Text>
                  <Text style={[s.previewTitle, { fontSize: previewSize, lineHeight: previewSize * 25 / 21 }]}>{selectedPlace.placeName || "Saved place"}</Text>
                  <Text style={s.placeCity}>{selectedPlace.city}</Text>
                  <Text style={s.previewAction}>Details →</Text>
                </View>
              </Pressable>}
            </View>}
            {error && <ErrorLine error={error} onRetry={onRefresh} />}
          </>}
          renderItem={({ item, index }) => <View>
            {(index === 0 || item.city !== visible[index - 1].city) && <View style={s.cityDivider}>
              <Text style={s.cityHeading}>{item.city || "Saved places"}</Text><View style={s.cityRule} />
              <Text style={s.cityCount}>{cityCounts.get(item.city) ?? 0}</Text>
            </View>}
            <PlaceRow item={item} expanded={opened === item.id}
              onPress={() => { setOpened(opened === item.id ? undefined : item.id); setSelected(opened !== item.id && exactMapPoint(item) ? item.id : undefined); }}
              onEdit={() => onSelect(item.id, "edit")}
              onShowMap={() => {
                if (!exactMapPoint(item)) { onSelect(item.id, "view"); return; }
                setSelected(item.id); list.current?.scrollToOffset({ offset: 0, animated: motion });
              }} />
          </View>}
          ListEmptyComponent={<WWEmpty title={items.length ? "No matching places" : review ? "All caught up" : "No saved places here"}
            body={items.length ? "Try another category, city or search." : undefined} />}
        />
      </Animated.View>
    </View>
  );
}function PlaceRow({
  item,
  onPress,
  expanded,
  onEdit,
  onShowMap,
}: {
  item: DreamItem;
  onPress: () => void;
  expanded: boolean;
  onEdit: () => void;
  onShowMap: () => void;
}) {
  const processing = item.status === "processing" || item.status === "created";
  const copy = React.useMemo(() => dreamCopy(item), [item]);
  const [showOriginal, setShowOriginal] = React.useState(false);
  return (
    <View style={[s.placePaper, expanded && s.placePaperOpen]}>
      <Pressable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        style={({ pressed }) => [
          s.place,
          pressed && { backgroundColor: colors.paperDeep },
        ]}
      >
        <View style={[s.thumbnail, !item.thumbnailUrl && s.symbolThumbnail]}>
          <DreamPhoto item={item} compact />
        </View>
        <View style={s.placeCopy}>
          <View style={s.placeCategory}>
            <Text style={s.placeType}>{categoryLabel(item.category)}</Text>
          </View>
          <Text style={s.placeTitle} numberOfLines={2}>
            {item.placeName || item.city || "Saved inspiration"}
          </Text>
          <Text style={s.placeCity} numberOfLines={1}>
            {[item.city, item.regionOrNeighborhood]
              .filter(Boolean)
              .join(" · ") ||
              item.country ||
              "Location to review"}
          </Text>
          {item.status === "failed" || item.needsReview || processing ? (
            <Text style={s.status}>
              {processing
                ? "Reading post…"
                : item.status === "failed"
                  ? "Save needs attention"
                  : "Review place"}
            </Text>
          ) : (
            locationNote(item) && <Text style={s.pinNote}>{locationNote(item)}</Text>
          )}
        </View>
        <WWIcon
          name={expanded ? "close" : "plus"}
          size={17}
          color={colors.mutedInk}
        />
      </Pressable>
      {expanded && (
        <View style={s.placeBody}>
          {item.thumbnailUrl && (
            <View style={s.expandedPhoto}>
              <DreamPhoto item={item} />
            </View>
          )}
          {copy.summary ? <Text style={s.placeSummary}>{copy.summary}</Text> : null}
          {copy.original && <View>
            <Pressable style={s.placeAction} accessibilityRole="button"
              accessibilityState={{ expanded: showOriginal }} onPress={() => setShowOriginal(!showOriginal)}>
              <Text style={s.actionText}>{showOriginal ? "Hide original text" : "Original post text"}</Text>
            </Pressable>
            {showOriginal && <Text selectable style={s.placeSummary}>{copy.original}</Text>}
          </View>}
          {item.locationAddress || item.regionOrNeighborhood ? (
            <View style={s.addressLine}>
              <WWIcon name="pin" size={15} />
              <Text style={s.addressText}>
                {item.locationAddress || [item.regionOrNeighborhood, item.city]
                  .filter(Boolean)
                  .join(", ")}
              </Text>
            </View>
          ) : null}
          <View style={s.placeActions}>
            <Pressable accessibilityRole="button" onPress={onShowMap} style={s.placeAction}>
              <Text style={s.actionText}>
                {exactMapPoint(item) ? "Show on map" : item.locationStatus === "needs_review" ? "Check location" : "Location details"}
              </Text>
            </Pressable>
            {safeWebUrl(item.sourceUrl) && (
              <Pressable
                accessibilityRole="link"
                onPress={() =>
                  void Linking.openURL(safeWebUrl(item.sourceUrl)!).catch(
                    () => {},
                  )
                }
                style={s.placeAction}
              >
                <Text style={s.actionText}>Source ↗</Text>
              </Pressable>
            )}
            {!processing && /^\d+$/.test(item.id) && <Pressable accessibilityRole="button" onPress={onEdit} style={s.placeAction}>
              <Text style={s.actionText}>Edit</Text>
            </Pressable>}
          </View>
        </View>
      )}
    </View>
  );
}
function ErrorLine({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <Pressable onPress={onRetry} style={s.notice}>
      <Text accessibilityRole="alert" style={s.error}>
        {error} · Tap to retry
      </Text>
    </Pressable>
  );
}
function CapturePlace({
  onClose,
  onSave,
  visible,
  onCloseRequestChange,
}: {
  onClose: () => void;
  onSave: (url: string, caption?: string) => boolean;
  visible: boolean;
  onCloseRequestChange?: (handler: (() => void) | null) => void;
}) {
  const insets = useSafeAreaInsets(),
    [url, setUrl] = React.useState(""),
    [caption, setCaption] = React.useState(""),
    [discarding, setDiscarding] = React.useState(false),
    [error, setError] = React.useState(false);
  const reducedMotion = useReducedMotion();
  const requestClose = () => {
    if (discarding) setDiscarding(false);
    else if (url.trim() || caption.trim()) setDiscarding(true);
    else onClose();
  };
  const closeRequest = React.useRef(requestClose); closeRequest.current = requestClose;
  React.useEffect(() => {
    onCloseRequestChange?.(visible ? () => closeRequest.current() : null);
    return () => onCloseRequestChange?.(null);
  }, [visible, onCloseRequestChange]);
  return (
    <Modal
      visible={visible}
      animationType={reducedMotion ? "none" : "slide"}
      presentationStyle="pageSheet"
      onRequestClose={requestClose}
    >
      <KeyboardAvoidingView
        style={[s.screen, { paddingTop: insets.top }]}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <WWHeader
          title="Save a place"
          action={
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close"
              onPress={requestClose}
              style={s.icon}
            >
              <WWIcon name="close" />
            </Pressable>
          }
        />
        {discarding ? <View style={{ padding: 24 }}>
          <Text style={s.captureBody}>Discard this unsaved place?</Text>
          <View style={s.placeActions}>
            <WWButton label="Keep editing" onPress={() => setDiscarding(false)} />
            <WWButton label="Discard" secondary onPress={onClose} />
          </View>
        </View> : <ScrollView
          keyboardShouldPersistTaps="handled"
          contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 32 }}
        >
          <Text style={s.captureBody}>
            Paste an Instagram post or reel. You can also share directly to
            Trotter from Instagram.
          </Text>
          <Text style={s.inputLabel}>Instagram link</Text>
          <TextInput
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            value={url}
            onChangeText={(value) => {
              setUrl(value);
              setError(false);
            }}
            placeholder="https://www.instagram.com/reel/…"
            placeholderTextColor={colors.mutedInk}
            accessibilityLabel="Instagram link"
            style={s.captureInput}
          />
          <Text style={s.inputLabel}>Caption (optional)</Text>
          <TextInput
            value={caption}
            onChangeText={setCaption}
            multiline
            placeholder="Add the original caption to help identify the place"
            placeholderTextColor={colors.mutedInk}
            accessibilityLabel="Original caption"
            style={[s.captureInput, s.caption]}
          />
          {error && (
            <Text accessibilityRole="alert" style={s.error}>
              Paste a valid Instagram post or reel link.
            </Text>
          )}
          <View style={{ marginTop: 20 }}>
            <WWButton
              label="Save place"
              disabled={!url.trim()}
              onPress={() => {
                if (onSave(url, caption)) onClose();
                else setError(true);
              }}
            />
          </View>
        </ScrollView>}
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  countryScreen: { flex: 1, minHeight: 0 },
  countryContent: { flex: 1, minHeight: 0 },
  countryHeader: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 24, paddingTop: 15, paddingBottom: 15,
    backgroundColor: colors.paperPhoto, borderBottomWidth: 1, borderBottomColor: colors.paperBorder },
  countryHeadingCopy: { flex: 1, minWidth: 0 },
  headerIcon: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  filterPanel: { paddingTop: 10, backgroundColor: colors.paperSoft },
  mapPreview: { flexDirection: "row", padding: 12, gap: 12, borderTopWidth: 1, borderTopColor: colors.paperBorder, alignItems: "center" },
  previewPhoto: { width: 50, height: 60, overflow: "hidden", backgroundColor: colors.paperDeep },
  previewTitle: { fontFamily: fonts.display, fontSize: 21, lineHeight: 25, color: colors.ink },
  previewAction: { fontFamily: fonts.sansSemi, fontSize: 12, lineHeight: 20, color: colors.blue, marginTop: 8 },
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  icon: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 22,
  },
  homeMeta: {
    marginHorizontal: 24,
    marginTop: -9,
    marginBottom: 23,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  meta: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  reviewButton: {
    minHeight: 35,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  reviewText: { fontFamily: fonts.sansSemi, fontSize: 11, color: colors.red },
  notice: {
    marginHorizontal: 24,
    marginBottom: 18,
    padding: 12,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paper,
  },
  noticeText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
  },
  error: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 18,
    color: colors.red,
  },
  countryMeta: {
    marginHorizontal: 20,
    marginTop: 4,
    marginBottom: 15,
    paddingHorizontal: 17,
    paddingTop: 17,
    paddingBottom: 22,
    borderWidth: 1,
    borderColor: "#d0d1bf",
    backgroundColor: colors.paperPhoto,
    overflow: "hidden",
  },
  countryTitle: {
    fontFamily: fonts.displayItalic,
    fontSize: 43,
    lineHeight: 47,
    letterSpacing: -1,
    color: colors.ink,
    marginBottom: 9,
    includeFontPadding: false,
  },
  mapPaper: {
    marginHorizontal: 24,
    padding: 0,
    paddingBottom: 0,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperSheet,
    marginBottom: 18,
  },
  mapFoot: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 10,
    paddingVertical: 11,
    paddingHorizontal: 11,
  },
  mapCount: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    color: colors.mutedInk,
  },
  mapSelection: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    padding: 12,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
  },
  mapSelectionTitle: {
    flex: 1,
    fontFamily: fonts.display,
    fontSize: 23,
    color: colors.ink,
  },
  mapNote: {
    fontFamily: fonts.sansRegular,
    fontSize: 10,
    color: colors.mutedInk,
    flexShrink: 1,
  },
  findingNote: { paddingHorizontal: 12, paddingBottom: 12, fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  search: {
    marginHorizontal: 24,
    minHeight: 46,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.ink,
    backgroundColor: colors.paper,
    marginBottom: 12,
  },
  cityFilters: { paddingHorizontal: 24, gap: 7, paddingBottom: 7 },
  city: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 3,
  },
  cityActive: { borderColor: colors.blue, backgroundColor: "#e5e9e0" },
  cityText: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    color: colors.mutedInk,
  },
  cityTextActive: { color: colors.blue },
  categories: { paddingHorizontal: 24, gap: 7, paddingBottom: 10 },
  category: {
    paddingVertical: 10,
    paddingHorizontal: 12,
    minHeight: 44,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 3,
  },
  categoryActive: { borderColor: colors.blue, backgroundColor: "#e4eade" },
  categoryText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
  },
  categoryTextActive: { color: colors.blue, fontFamily: fonts.sansSemi },
  filterCount: {
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    color: colors.mutedInk,
  },
  cityDivider: {
    marginHorizontal: 24,
    marginTop: 15,
    marginBottom: 13,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  cityHeading: {
    fontFamily: fonts.displayItalic,
    fontSize: 25,
    lineHeight: 29,
    color: colors.ink,
    includeFontPadding: false,
  },
  cityRule: { flex: 1, height: 1, backgroundColor: colors.paperBorder },
  cityCount: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
  },
  placePaper: {
    marginHorizontal: 24,
    marginBottom: 9,
    borderWidth: 1,
    borderColor: "#d2d4c3",
    backgroundColor: colors.paperPhoto,
    shadowColor: "#284e62",
    shadowOpacity: 0.03,
    shadowOffset: { width: 0, height: 2 },
    shadowRadius: 1,
  },
  placePaperOpen: { borderColor: "#9eb1a8" },
  listHeading: {
    marginHorizontal: 24,
    flexDirection: "row",
    justifyContent: "space-between",
    paddingBottom: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.paperBorder,
  },
  sectionLabel: {
    fontFamily: fonts.mono,
    fontSize: 9,
    letterSpacing: 1,
    color: colors.blue,
  },
  listCount: { fontFamily: fonts.mono, fontSize: 9, color: colors.mutedInk },
  place: {
    paddingVertical: 13,
    paddingHorizontal: 12,
    minHeight: 96,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  thumbnail: {
    width: 56,
    height: 65,
    padding: 4,
    borderWidth: 1,
    borderColor: "#d0d2bf",
    backgroundColor: colors.paperPhoto,
    transform: [{ rotate: "-2deg" }],
    overflow: "hidden",
  },
  symbolThumbnail: {
    padding: 0,
    borderWidth: 1,
    borderStyle: "dashed",
    transform: [{ rotate: "0deg" }],
  },
  placeCopy: { flex: 1, minWidth: 0 },
  placeCategory: {
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
    marginBottom: 5,
  },
  placeType: {
    fontFamily: fonts.sans,
    fontSize: 11,
    letterSpacing: 0.6,
    textTransform: "uppercase",
    color: colors.blue,
  },
  placeTitle: {
    fontFamily: fonts.display,
    fontSize: 23,
    lineHeight: 26,
    color: colors.ink,
    letterSpacing: -0.35,
    includeFontPadding: false,
  },
  placeCity: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
    marginTop: 6,
  },
  status: {
    fontFamily: fonts.sansSemi,
    fontSize: 10,
    color: colors.red,
    marginTop: 6,
  },
  pinNote: {
    fontFamily: fonts.sansRegular,
    fontSize: 9,
    color: colors.mutedInk,
    marginTop: 6,
  },
  placeBody: {
    marginHorizontal: 12,
    paddingHorizontal: 1,
    paddingBottom: 13,
    borderTopWidth: 1,
    borderTopColor: "#d2d4c3",
    borderStyle: "dashed",
  },
  expandedPhoto: { height: 176, marginTop: 17, marginBottom: 14 },
  placeSummary: {
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    lineHeight: 23,
    color: colors.mutedInk,
    marginVertical: 13,
  },
  addressLine: {
    flexDirection: "row",
    gap: 8,
    alignItems: "flex-start",
    marginTop: 9,
  },
  addressText: {
    flex: 1,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 21,
    color: colors.mutedInk,
  },
  placeActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 13,
    marginTop: 10,
  },
  placeAction: { minHeight: 44, justifyContent: "center" },
  actionText: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.ink,
  },
  captureBody: {
    fontFamily: fonts.sansRegular,
    fontSize: 15,
    lineHeight: 23,
    color: colors.mutedInk,
    marginBottom: 26,
  },
  inputLabel: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    color: colors.ink,
    marginBottom: 8,
    marginTop: 16,
  },
  captureInput: {
    minHeight: 48,
    paddingHorizontal: 12,
    paddingVertical: 12,
    borderColor: colors.paperBorder,
    borderWidth: 1,
    borderRadius: 3,
    backgroundColor: colors.paper,
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    color: colors.ink,
  },
  caption: { minHeight: 110, textAlignVertical: "top" },
});
