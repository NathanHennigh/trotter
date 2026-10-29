import React from "react";
import {
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
import { BottomNav } from "../components/trotter/TrotterKit";
import {
  WWButton,
  WWEmpty,
  WWHeader,
  WWIcon,
} from "../components/world-window/WorldWindowUI";
import { DreamCountryTransition } from "../components/world-window/dreams/DreamCountryTransition";
import { CountryPostcard } from "../components/world-window/dreams/CountryPostcard";
import { DreamEditor } from "../components/world-window/dreams/DreamEditor";
import { DreamPhoto, PlaceSymbol } from "../components/world-window/dreams/DreamPhoto";
import {
  normalizeName,
  type CountryBoard,
  dreamLocationType,
  destinationNames,
  dreamDestination,
  countryBoards,
  countryKey,
  dreamSourceKey,
  placesFromSource,
  sourcePlaceCounts,
  exactMapPoint,
  safeWebUrl,
} from "../components/world-window/dreams/dreamPresentation";
import { browseDreams, browseTypes, needsDreamAttention, type BrowseType, type BrowseSort } from "../components/world-window/dreams/dreamBrowse";
import { countryRegion } from "../components/world-window/dreams/countryRegion";
import { dreamCardTitle, dreamCardMeta, dreamCardExcerpt, repeatedDreamTitleIds } from "../components/world-window/dreams/dreamCardPresentation";
import { dreamProcessingState } from "../components/world-window/dreams/dreamProcessing";
import { canFindLocation, isSavedInspiration, locationNote } from "../components/world-window/dreams/locationPresentation";
import { DreamPlacesMap } from "../components/world-window/dreams/DreamPlacesMap";
import type { MapPoint } from "../components/world-window/trips/tripPresentation";
import type { BottomNavTab } from "../data/trotterMock";
import { DreamItem, useDreams } from "../services/dreams";
import { acknowledgeNativeDreamShare, listNativeDreamShareReceipts, retryNativeDreamShare, type NativeDreamShareReceipt } from "../services/nativeDreamShare";
import { colors, fonts, layout } from "../theme/trotterTheme";
import { PressFeedback as Pressable, useReducedMotion } from "../components/world-window/motion";
import { ProfileAvatar } from "../components/world-window/profile/ProfileAvatar";
import { DreamTripPicker, type PlannerEntry } from "../components/world-window/planner/DreamTripPicker";

export function DreamsScreen({
  active,
  onChange,
  visible = true,
  onBackHandlerChange,
  openSource,
  onOpenPlanner,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
  visible?: boolean;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void;
  openSource?: { url: string; requestId: number; receiptId?: string };
  onOpenPlanner?: (entry: PlannerEntry) => void;
}) {
  const insets = useSafeAreaInsets(),
    store = useDreams();
  const reducedMotion = useReducedMotion();
  const [country, setCountry] = React.useState<{
      key: string;
      title: string;
    }>(),
    [capture, setCapture] = React.useState(false),
    [selectedMode, setSelectedMode] = React.useState<"view" | "edit" | "location">("view"),
    [countryClosing, setCountryClosing] = React.useState(false),
    [selectedId, setSelectedId] = React.useState<string>();
  const [libraryQuery, setLibraryQuery] = React.useState("");
  const [captureReceipt, setCaptureReceipt] = React.useState(false);
  const [tripPicker, setTripPicker] = React.useState<{ items: DreamItem[]; sourceUrl?: string; destination?: string }>();
  React.useEffect(() => {
    if (!captureReceipt) return;
    const timer = setTimeout(() => setCaptureReceipt(false), 5000);
    return () => clearTimeout(timer);
  }, [captureReceipt]);
  const [sourceUrl, setSourceUrl] = React.useState<string>();
  const [nativeReceipt, setNativeReceipt] = React.useState<NativeDreamShareReceipt>();
  React.useEffect(() => {
    if (!openSource) return;
    setSourceUrl(openSource.url); setCountry(undefined);
    setSelectedId(undefined); setCapture(false); setNativeReceipt(undefined);
  }, [openSource?.requestId]);
  const editorBack = React.useRef<(() => void) | null>(null),
    captureBack = React.useRef<(() => void) | null>(null),
    countryBack = React.useRef<(() => void) | null>(null),
    sourceBack = React.useRef<(() => void) | null>(null);
  const registerEditorBack = React.useCallback((handler: (() => void) | null) => { editorBack.current = handler; }, []);
  const registerSourceBack = React.useCallback((handler: (() => void) | null) => { sourceBack.current = handler; }, []);
  const registerCountryBack = React.useCallback((handler: (() => void) | null) => { countryBack.current = handler; }, []);
  const registerCaptureBack = React.useCallback((handler: (() => void) | null) => { captureBack.current = handler; }, []);
  const homeOffset = React.useRef(0),
    selected = store.items.find((item) => item.id === selectedId);
  const boards = React.useMemo(() => countryBoards(store.items).filter(board => board.key !== "unsorted"), [store.items]);
  const unsortedItems = React.useMemo(() => store.items.filter(item => countryKey(item.country) === "unsorted"), [store.items]);
  const attentionItems = React.useMemo(() => store.items.filter(needsDreamAttention), [store.items]);
  const inspirationItems = React.useMemo(() => unsortedItems.filter(item => isSavedInspiration(item) && !needsDreamAttention(item)), [unsortedItems]);
  const organizingItems = React.useMemo(() => unsortedItems.filter(item => !needsDreamAttention(item) && !isSavedInspiration(item)), [unsortedItems]);
  const searchItems = React.useMemo(() => browseDreams(store.items, libraryQuery), [store.items, libraryQuery]);
  const repeatedSearchTitles = React.useMemo(() => repeatedDreamTitleIds(searchItems), [searchItems]);
  const sourceCounts = React.useMemo(() => sourcePlaceCounts(store.items), [store.items]);
  const sourceItems = React.useMemo(() => sourceUrl ? placesFromSource(store.items, sourceUrl) : [], [store.items, sourceUrl]);
  const sourceItemsRef = React.useRef(sourceItems); sourceItemsRef.current = sourceItems;
  React.useEffect(() => {
    if (!visible || !sourceUrl || !openSource?.receiptId || dreamSourceKey(sourceUrl) !== dreamSourceKey(openSource.url)) return;
    let disposed = false, timer: ReturnType<typeof setTimeout>, lastStatus: string | undefined;
    const poll = async () => {
      try {
        const receipts = await listNativeDreamShareReceipts();
        if (disposed) return;
        const receipt = receipts.find(value => value.id === openSource.receiptId);
        setNativeReceipt(receipt);
        // Quiet refresh absorbs network failures. Keep trying while the accepted
        // item is absent, rather than treating its receipt status as a successful fetch.
        if (receipt?.status === "saved" && !sourceItemsRef.current.some(item => item.id === String(receipt.itemId))) await store.refresh("quiet");
        if (disposed) return;
        if (receipt?.status === "saved" && sourceItemsRef.current.some(item => item.id === String(receipt.itemId))) {
          await acknowledgeNativeDreamShare(receipt.id);
          if (!disposed) setNativeReceipt(undefined);
          return;
        }
        if (!receipt) return;
        lastStatus = receipt?.status;
      } catch { /* The native receipt retains the link even if its bridge is briefly unavailable. */ }
      if (!disposed) timer = setTimeout(() => void poll(), lastStatus === "saved" ? 5000 : 1500);
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [visible, sourceUrl, openSource?.requestId, store.refresh]);
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
      country?.key === "unsorted" ? attentionItems : country?.key === "organizing" ? organizingItems : country?.key === "inspiration" ? inspirationItems : store.items.filter((item) => countryKey(item.country) === country?.key),
    [store.items, country?.key, attentionItems, organizingItems, inspirationItems],
  );
  const openCountry = (value: { key: string; title: string }) => { setCountryClosing(false); setCountry(value); };
  const back = () => {
    if (sourceUrl) { setSourceUrl(undefined); return; }
    if (reducedMotion) setCountry(undefined);
    else setCountryClosing(true);
  };
  React.useEffect(() => {
    const goBack = () => {
      if (!visible) return false;
      if (capture && captureBack.current) { captureBack.current(); return true; }
      if (selected && editorBack.current) { editorBack.current(); return true; }
      if (!country && !sourceUrl) return false;
      if (sourceUrl && sourceBack.current) sourceBack.current();
      else if (countryBack.current) countryBack.current(); else back();
      return true;
    };
    onBackHandlerChange?.(visible ? goBack : null);
    const handler = !onBackHandlerChange && visible
      ? BackHandler.addEventListener("hardwareBackPress", goBack) : undefined;
    return () => { handler?.remove(); onBackHandlerChange?.(null); };
  }, [country, sourceUrl, visible, selected, capture, onBackHandlerChange]);
  const loading = store.status === "loading" || store.status === "refreshing";
  const actions = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Save from Instagram"
      onPress={() => setCapture(true)}
      style={s.icon}
    >
      <WWIcon name="plus" size={23} />
    </Pressable>
  );
  return (
    <View style={[s.screen, { paddingTop: insets.top }]}>
      <View style={{ flex: 1, display: sourceUrl ? "none" : "flex" }} accessibilityElementsHidden={Boolean(sourceUrl)} importantForAccessibility={sourceUrl ? "no-hide-descendants" : "auto"}>
      <DreamCountryTransition open={Boolean(country) && !countryClosing} reducedMotion={reducedMotion}
        onClosed={() => { setCountry(undefined); setCountryClosing(false); }} detail={country ? (
        <CountryPlaces key={country.key} title={country.title} items={countryItems}
          inbox={["unsorted", "organizing", "inspiration"].includes(country.key)}
          topInset={0} bottomInset={insets.bottom} loading={loading} error={store.error}
          onBack={back} motion={!reducedMotion} active={visible && !sourceUrl && !countryClosing}
          onBackRequestChange={registerCountryBack} onRefresh={() => void store.refresh()}
          onSelect={(id, mode = "view") => { setSelectedMode(mode); setSelectedId(id); }}
          onShowSource={setSourceUrl} onCapture={() => setCapture(true)} onLocateMissing={store.locateMissing}
          onPlanTrip={onOpenPlanner && !["unsorted", "organizing", "inspiration"].includes(country.key) ? () => setTripPicker({ items: countryItems, destination: country.title }) : undefined}
          onRetryItem={async item => { await store.shareInstagramLinkDurable(item.sourceUrl, item.caption); }} />
      ) : undefined} library={(
        <FlatList<CountryBoard | DreamItem>
          data={libraryQuery.trim() ? searchItems : boards}
          keyExtractor={(item) => "key" in item ? item.key : item.id}
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
              <WWHeader title="Dreams" action={<View style={{ flexDirection: "row", alignItems: "center" }}>{actions}<ProfileAvatar onPress={() => onChange("profile")} /></View>} />
              <View style={s.librarySearch}><WWIcon name="search" size={18} /><TextInput value={libraryQuery} onChangeText={setLibraryQuery} accessibilityLabel="Search all saved places" placeholder="Find a place, city, or country" placeholderTextColor={colors.mutedInk} style={s.searchInput} returnKeyType="search" onSubmitEditing={Keyboard.dismiss} /></View>
              {!libraryQuery.trim() && attentionItems.length > 0 && (
                <Pressable accessibilityRole="button" accessibilityLabel={`Needs attention, ${attentionItems.length} ${attentionItems.length === 1 ? "save" : "saves"}`}
                  onPress={() => { openCountry({ key: "unsorted", title: "Needs attention" }); }}
                  accessibilityHint="Review saves that need details or a retry"
                  style={s.inbox}>
                  <Text accessibilityLiveRegion="polite" style={s.inboxTitle}>Needs attention <Text style={s.inboxCount}>· {attentionItems.length}</Text></Text>
                  <WWIcon name="chevron" size={14} color={colors.mutedInk} />
                </Pressable>
              )}
              {!libraryQuery.trim() && organizingItems.length > 0 && <Pressable accessibilityRole="button" accessibilityLabel={`Organizing ${organizingItems.length} saves`} onPress={() => openCountry({ key: "organizing", title: "Organizing saves" })} style={s.organizing}><Text style={s.browseSummary}>Organizing {organizingItems.length} saves</Text><WWIcon name="chevron" size={14} /></Pressable>}
              {!libraryQuery.trim() && inspirationItems.length > 0 && <Pressable accessibilityRole="button" accessibilityLabel={`Saved inspiration, ${inspirationItems.length} posts`} onPress={() => openCountry({ key: "inspiration", title: "Saved inspiration" })} style={s.organizing}><View style={s.placeCopy}><Text style={s.inspirationTitle}>Saved inspiration · {inspirationItems.length}</Text><Text style={s.inboxSummary}>Posts without a destination yet</Text></View><WWIcon name="chevron" size={14} /></Pressable>}
              {libraryQuery.trim() && <View style={s.listMeta}><Text style={s.browseSummary}>{searchItems.length} matching places</Text><Pressable accessibilityRole="button" onPress={() => setLibraryQuery("")} style={s.metaAction}><Text style={s.actionText}>Clear search</Text></Pressable></View>}
              {store.error && (
                <ErrorLine
                  error={store.error}
                  onRetry={() => void store.refresh()}
                />
              )}
            </>
          }
          renderItem={({ item }) => "key" in item ? (
            <CountryPostcard
              board={item}
              visible={visible && !country && !sourceUrl}
              onPress={() => { openCountry({ key: item.key, title: item.title }); }}
            />
          ) : <PlaceRow item={item} excerpt={repeatedSearchTitles.has(item.id) ? dreamCardExcerpt(item) : undefined} onPress={() => { setSelectedMode("view"); setSelectedId(item.id); }} onEdit={() => { setSelectedMode("location"); setSelectedId(item.id); }} />}
          ListEmptyComponent={!libraryQuery.trim() && unsortedItems.length ? null : (
            <WWEmpty
              title={
                libraryQuery.trim() ? "No matching places" : loading ? "Loading your saved places…" : "Your next places"
              }
              body={
                loading
                  ? undefined
                  : libraryQuery.trim() ? "Try a place name, destination, or a word from your saved posts." : "Share an Instagram post to Trotter, or paste its link here. Your saves come together by country."
              }
              action={
                !loading ? (
                  <WWButton
                    label={libraryQuery.trim() ? "Clear search" : "Save from Instagram"}
                    onPress={() => libraryQuery.trim() ? setLibraryQuery("") : setCapture(true)}
                  />
                ) : undefined
              }
            />
          )}
        />
      )} />
      </View>
      {sourceUrl && <CountryPlaces key={sourceUrl} title="Places from this post" items={sourceItems} sourceUrl={sourceUrl}
        onPlanTrip={onOpenPlanner ? () => setTripPicker({ items: sourceItems, sourceUrl, destination: sourceItems.find(item => item.country)?.country }) : undefined}
        sourceReceipt={nativeReceipt && dreamSourceKey(sourceUrl) === dreamSourceKey(nativeReceipt.sourceUrl) ? nativeReceipt : undefined}
        onRetryShare={nativeReceipt ? () => void retryNativeDreamShare(nativeReceipt.id).catch(() => {}) : undefined}
        topInset={0} bottomInset={insets.bottom} loading={loading} error={store.error} onBack={back}
        motion={!reducedMotion} active={visible} onBackRequestChange={registerSourceBack}
        onRefresh={() => void store.refresh()} onSelect={(id, mode = "view") => { setSelectedMode(mode); setSelectedId(id); }} onLocateMissing={store.locateMissing} />}
      <BottomNav active={active} onChange={onChange} />
      {tripPicker && onOpenPlanner ? <DreamTripPicker {...tripPicker} visible={visible} onClose={() => setTripPicker(undefined)} onOpenPlanner={onOpenPlanner} /> : null}
      {captureReceipt && visible && <View pointerEvents="none" style={[s.savedReceipt, { bottom: insets.bottom + layout.bottomNavHeight + 12 }]}><Text accessibilityLiveRegion="polite" style={s.savedReceiptText}>Saved on this phone. We’ll organize it in Dreams.</Text></View>}
      {selected && (
        <DreamEditor
          key={selected.id}
          visible={visible}
          initialMode={selectedMode}
          onCloseRequestChange={registerEditorBack}
          item={selected}
          points={pointsByCountry.get(countryKey(selected.country)) ?? []}
          sourceCount={sourceCounts.get(dreamSourceKey(selected.sourceUrl)) ?? 1}
          onShowSource={() => { setSourceUrl(selected.sourceUrl); setSelectedId(undefined); }}
          onClose={() => setSelectedId(undefined)}
          onSave={store.updateItem}
          onDelete={store.deleteItem}
          onLocate={store.locateItem}
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
          onSave={async (url, caption) => {
            await store.shareInstagramLinkDurable(url, caption);
            setCaptureReceipt(true);
            return true;
          }}
        />
      )}
    </View>
  );
}

function CountryPlaces({
  title, items, topInset, bottomInset, loading, error, onBack, onRefresh,
  onSelect, onLocateMissing, motion, active = true, onBackRequestChange,
  sourceUrl, sourceReceipt, onRetryShare, onCapture, inbox = false, onRetryItem, onShowSource, onPlanTrip,
}: {
  title: string; items: DreamItem[]; topInset: number; bottomInset: number;
  loading: boolean; error?: string; onBack: () => void; onRefresh: () => void;
  onSelect: (id: string, mode?: "view" | "edit" | "location") => void;
  onLocateMissing: (ids: string[]) => Promise<void>; motion: boolean; active?: boolean;
  onBackRequestChange?: (handler: (() => void) | null) => void;
  sourceUrl?: string; sourceReceipt?: NativeDreamShareReceipt; onRetryShare?: () => void;
  onCapture?: () => void; inbox?: boolean; onShowSource?: (url: string) => void;
  onRetryItem?: (item: DreamItem) => Promise<void>;
  onPlanTrip?: () => void;
}) {
  const { height, fontScale } = useWindowDimensions();
  const [query, setQuery] = React.useState(""), [city, setCity] = React.useState(""),
    [type, setType] = React.useState<BrowseType>("All types"),
    [sort, setSort] = React.useState<BrowseSort>("recent"),
    [view, setView] = React.useState<"places" | "map">("places"),
    [filters, setFilters] = React.useState(false), [cityQuery, setCityQuery] = React.useState(""),
    [selected, setSelected] = React.useState<string>(), [missingOpen, setMissingOpen] = React.useState(false),
    [queueing, setQueueing] = React.useState(false);
  const queueLock = React.useRef(false), mounted = React.useRef(true);
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const list = React.useRef<FlatList<DreamItem>>(null);
  const unsorted = inbox || (!sourceUrl && countryKey(title) === "unsorted");
  const isCountry = !sourceUrl && !unsorted;
  const sourceTitle = sourceUrl && items[0]?.caption?.trim()
    ? dreamCardTitle({ ...items[0], placeName: undefined, coordinatePrecision: undefined, summary: "", city: undefined }) : "Places from this post";
  const cities = React.useMemo(() => destinationNames(items), [items]);
  const visible = React.useMemo(() => sourceUrl
    ? [...items].sort((a, b) => (a.sourcePlaceIndex ?? 0) - (b.sourcePlaceIndex ?? 0))
    : browseDreams(items, query, city, type, sort), [items, query, city, type, sort, sourceUrl]);
  const points = React.useMemo(() => visible.map(exactMapPoint).filter((p): p is MapPoint => Boolean(p)), [visible]);
  const selectedMapPlace = visible.find(item => item.id === selected && exactMapPoint(item));
  const selectedPlace = selectedMapPlace || visible.find(item => exactMapPoint(item));
  const missing = visible.filter(item => !exactMapPoint(item));
  const lookup = missing.filter(canFindLocation);
  const region = React.useMemo(() => countryRegion(title), [title]);
  const filtered = Boolean(query || city || type !== "All types");
  const postCounts = React.useMemo(() => sourcePlaceCounts(visible), [visible]);
  const repeatedTitles = React.useMemo(() => repeatedDreamTitleIds(items), [items]);
  const clear = () => { setQuery(""); setCity(""); setType("All types"); };
  const requestBack = () => {
    Keyboard.dismiss();
    if (filters) { setFilters(false); return; }
    if (missingOpen) { setMissingOpen(false); return; }
    if (view === "map") { setView("places"); return; }
    onBack();
  };
  const latestBack = React.useRef(requestBack); latestBack.current = requestBack;
  React.useEffect(() => {
    onBackRequestChange?.(active ? () => latestBack.current() : null);
    return () => onBackRequestChange?.(null);
  }, [active, onBackRequestChange]);
  React.useEffect(() => { if (city && !cities.some(value => normalizeName(value) === normalizeName(city))) setCity(""); }, [city, cities]);
  const findLocations = async () => {
    if (queueLock.current || !lookup.length) return;
    queueLock.current = true; setQueueing(true);
    try { await onLocateMissing(lookup.map(item => item.id)); }
    catch { /* The store exposes a retryable error and retains all saves. */ }
    finally { queueLock.current = false; if (mounted.current) setQueueing(false); }
  };
  const showOnMap = (id: string) => { setSelected(id); setView("map"); Keyboard.dismiss(); };
  const receiptNotice = sourceReceipt && sourceReceipt.status !== "saved" ? <View style={s.notice}>
    <Text accessibilityLiveRegion="polite" style={s.noticeText}>{sourceReceipt.status === "failed" ? "Saved on this phone. Couldn’t send it to Dreams."
      : sourceReceipt.status === "sign_in" ? "Your link is kept on this phone. Sign in to finish saving."
      : "Saved on this phone. We’ll send it when connected."}</Text>
    {sourceReceipt.status === "failed" && onRetryShare && <WWButton label="Retry upload" secondary onPress={onRetryShare} />}
  </View> : null;
  return <View style={[s.countryScreen, { paddingTop: topInset }]}>
    <View style={s.browseHeader}>
      <Pressable accessibilityRole="button" accessibilityLabel={sourceUrl ? "Back" : "Back to Dreams"} onPress={() => { Keyboard.dismiss(); onBack(); }} style={s.backLink}>
        <WWIcon name="back" size={17} /><Text style={s.backText}>{sourceUrl ? "Back" : "Dreams"}</Text>
      </Pressable>
      {sourceUrl && <Text style={s.sourceKicker}>FROM INSTAGRAM</Text>}
      <View style={s.browseTitleLine}>
        {isCountry && <View style={s.countryPhoto}><DreamPhoto artworkForCountry={title} item={items[0]} compact /></View>}
        <View style={s.placeCopy}>
          <Text accessibilityRole="header" numberOfLines={sourceUrl ? 3 : 2} style={[s.browseTitle, sourceUrl && s.sourceTitle]}>{unsorted ? title : sourceUrl ? sourceTitle : title}</Text>
          <Text style={s.browseSummary}>{unsorted ? title === "Saved inspiration" ? "Keep these posts for later. Add a destination whenever you know it." : title === "Organizing saves" ? "Your posts are saved. We’re organizing them." : "Your saves are safe. Choose what to retry or add." : `${items.length} ${items.length === 1 ? "place" : "places"}${isCountry && cities.length > 1 ? ` · ${cities.length} destinations` : sourceUrl ? " from this post" : ""}`}</Text>
        </View>
        {isCountry && onCapture && <Pressable accessibilityRole="button" accessibilityLabel="Save from Instagram" onPress={() => { Keyboard.dismiss(); onCapture(); }} style={s.addButton}><WWIcon name="plus" size={20} /></Pressable>}
      </View>
      {sourceUrl && safeWebUrl(sourceUrl) && <Pressable style={s.backLink} accessibilityRole="link" accessibilityLabel="View original post" onPress={() => void Linking.openURL(safeWebUrl(sourceUrl)!).catch(() => {})}><Text style={s.actionText}>View original post</Text><WWIcon name="arrow" size={15} /></Pressable>}
      {onPlanTrip ? <Pressable style={sourceUrl ? s.backLink : s.planTrip} accessibilityRole="button" accessibilityLabel={sourceUrl ? "Add this post to a trip" : `Plan a trip with your ${title} saves`} onPress={() => { Keyboard.dismiss(); onPlanTrip(); }}><WWIcon name="planner" size={sourceUrl ? 17 : 21} color={sourceUrl ? colors.blue : colors.paperSoft} /><Text style={sourceUrl ? s.actionText : s.planTripText}>{sourceUrl ? "Add to a trip" : "Plan a trip"}</Text></Pressable> : null}
    </View>
    {isCountry && <View style={s.viewTabs}>
      {(["places", "map"] as const).map(value => <Pressable key={value} accessibilityRole="tab" accessibilityLabel={value === "places" ? "Show saved places" : "Show map"} accessibilityState={{ selected: view === value }} onPress={() => { setView(value); Keyboard.dismiss(); }} style={[s.viewTab, view === value && s.viewTabSelected]}><Text style={[s.viewTabText, view === value && s.viewTabTextSelected]}>{value === "places" ? "Places" : "Map"}</Text></Pressable>)}
    </View>}
    <View style={{ flex: 1, display: view === "places" || !isCountry ? "flex" : "none" }} accessibilityElementsHidden={view === "map"} importantForAccessibility={view === "map" ? "no-hide-descendants" : "auto"}>
    <FlatList ref={list} style={{ flex: 1 }}
      data={visible} keyExtractor={item => item.id} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag"
      showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: bottomInset + layout.bottomNavHeight + 24 }}
      initialNumToRender={8} windowSize={7} refreshControl={<RefreshControl refreshing={loading} onRefresh={onRefresh} tintColor={colors.blue} />}
      ListHeaderComponent={<>
        {isCountry && (items.length > 2 || filtered) && <>
          <View style={s.searchLine}><View style={s.searchBox}><WWIcon name="search" size={17} /><TextInput value={query} onChangeText={value => { setQuery(value); list.current?.scrollToOffset({ offset: 0, animated: false }); }} accessibilityLabel="Search country places" placeholder="Search your places" placeholderTextColor={colors.mutedInk} returnKeyType="search" onSubmitEditing={Keyboard.dismiss} style={s.searchInput} /></View>
            <Pressable accessibilityRole="button" accessibilityLabel="Filter places" accessibilityState={{ expanded: filters }} onPress={() => { Keyboard.dismiss(); setFilters(true); }} style={[s.filterButton, filtered && s.filterButtonActive]}><WWIcon name="filter" size={20} /></Pressable></View>
          {filtered && <View style={s.listMeta}><Text style={s.browseSummary}>{`${visible.length} of ${items.length} places${city ? ` · ${city}` : ""}${type !== "All types" ? ` · ${type}` : ""}`}</Text><Pressable accessibilityRole="button" onPress={clear} style={s.metaAction}><Text style={s.actionText}>Clear filters</Text></Pressable></View>}

        </>}
        {receiptNotice}
        {error && <ErrorLine error={error} onRetry={onRefresh} />}
      </>}
      renderItem={({ item, index }) => <View>
        {isCountry && sort === "city" && !city && cities.length > 1 && (index === 0 || normalizeName(dreamDestination(item)) !== normalizeName(dreamDestination(visible[index - 1]))) && <View style={s.cityDivider}><Text style={s.cityHeading}>{dreamDestination(item) || "Other places"}</Text><View style={s.cityRule} /></View>}
        {!sourceUrl && !unsorted && (postCounts.get(dreamSourceKey(item.sourceUrl)) || 0) > 1 && (index === 0 || dreamSourceKey(item.sourceUrl) !== dreamSourceKey(visible[index - 1].sourceUrl)) && <Pressable style={s.sourceGroup} accessibilityRole="button" accessibilityLabel="View places from this post" onPress={() => onShowSource?.(item.sourceUrl)}><Text style={s.sourceGroupText}>Places from this post</Text><WWIcon name="arrow" size={13} /></Pressable>}
        <PlaceRow item={item} excerpt={repeatedTitles.has(item.id) ? dreamCardExcerpt(item) : undefined} sharedPhoto={index > 0 && dreamSourceKey(item.sourceUrl) === dreamSourceKey(visible[index - 1].sourceUrl)} hideCity={Boolean(city)} inbox={unsorted} onPress={() => onSelect(item.id, "view")} onEdit={() => onSelect(item.id, "location")} onRetry={onRetryItem ? () => onRetryItem(item) : undefined} onShowMap={isCountry ? () => showOnMap(item.id) : undefined} />
      </View>}
      ListEmptyComponent={sourceReceipt && sourceReceipt.status !== "saved" && !items.length ? null : <WWEmpty title={loading ? "Loading your saves…" : items.length ? "No matching places" : unsorted ? "All caught up" : "No saved places here"} body={items.length ? "Try another search or see all your places." : undefined} action={items.length ? <WWButton label="Clear filters" onPress={clear} /> : undefined} />}
    />
    </View>
    {isCountry && view === "map" && <ScrollView style={s.countryContent} contentContainerStyle={{ paddingBottom: bottomInset + layout.bottomNavHeight + 24 }}>
      {points.length ? <>
        <DreamPlacesMap overview={region} points={points} fitKey={`${title}-${city}-${type}-${query}`} height={Math.max(240, Math.min(390, height * .43))} selectedId={selectedMapPlace?.id} onSelect={setSelected} />
        {selectedPlace && <Pressable accessibilityRole="button" accessibilityLabel={`Details for ${dreamCardTitle(selectedPlace)}`} onPress={() => onSelect(selectedPlace.id)} style={s.selectedPlace}><View style={s.previewPhoto}><DreamPhoto item={selectedPlace} compact /></View><View style={s.placeCopy}><Text style={s.previewTitle}>{dreamCardTitle(selectedPlace)}</Text><Text style={s.placeCity}>{dreamCardMeta(selectedPlace)}</Text></View><WWIcon name="chevron" size={17} /></Pressable>}
        <View style={s.listMeta}><Text style={s.browseSummary}>{points.length} of {visible.length} places on map</Text>{missing.length > 0 && <Pressable accessibilityRole="button" onPress={() => setMissingOpen(true)} style={s.metaAction}><Text style={s.actionText}>Review missing locations</Text></Pressable>}</View>
      </> : <WWEmpty title="Places first. Pins later." body="Your saves are here, even without exact locations." action={<View style={{ gap: 12 }}><WWButton label="Back to places" onPress={() => setView("places")} />{missing.length > 0 && <WWButton label="Add locations" secondary onPress={() => setMissingOpen(true)} />}</View>} />}
      {error && <ErrorLine error={error} onRetry={onRefresh} />}
    </ScrollView>}
    <Modal visible={active && (filters || missingOpen)} transparent animationType={motion ? "fade" : "none"} onRequestClose={() => { setFilters(false); setMissingOpen(false); }}>
      <View style={s.filterOverlay}><Pressable accessibilityRole="button" accessibilityLabel="Close panel" onPress={() => { setFilters(false); setMissingOpen(false); }} style={StyleSheet.absoluteFill} />
        <View style={[s.filterSheet, { maxHeight: height * .85, paddingBottom: Math.max(bottomInset, 20) }]} accessibilityViewIsModal>
          <View style={s.filterSheetHeader}><Text accessibilityRole="header" style={s.filterSheetTitle}>{missingOpen ? "Locations to confirm" : "Find your places"}</Text><Pressable accessibilityRole="button" accessibilityLabel="Close filters" onPress={() => { setFilters(false); setMissingOpen(false); }} style={s.headerIcon}><WWIcon name="close" /></Pressable></View>
          <ScrollView keyboardShouldPersistTaps="handled">
            {missingOpen ? <>
              {missing.map(item => <PlaceRow key={item.id} item={item} onPress={() => { setMissingOpen(false); onSelect(item.id); }} onEdit={() => { setMissingOpen(false); onSelect(item.id, "location"); }} />)}
              {lookup.length > 0 && <View style={s.filterPad}><WWButton label={queueing ? "Starting lookup…" : "Retry available locations"} disabled={queueing} secondary onPress={() => void findLocations()} /></View>}
            </> : <View style={s.filterPad}>
              <Text style={s.filterLabel}>Destination</Text>
              {cities.length > 8 && <TextInput value={cityQuery} onChangeText={setCityQuery} accessibilityLabel="Find a destination" placeholder="Find a destination" style={s.captureInput} />}
              <View style={s.filterChips}>{["", ...cities.filter(c => normalizeName(c).includes(normalizeName(cityQuery)))].map(value => <Pressable key={value || "all"} accessibilityRole="radio" accessibilityLabel={value || "All destinations"} accessibilityState={{ checked: city === value }} onPress={() => setCity(value)} style={[s.filterChip, city === value && s.filterChipSelected]}><Text style={s.filterChipText}>{value || "All destinations"}</Text></Pressable>)}</View>
              <Text style={s.filterLabel}>Type</Text><View style={s.filterChips}>{browseTypes.map(value => <Pressable key={value} accessibilityRole="radio" accessibilityLabel={value} accessibilityState={{ checked: type === value }} onPress={() => setType(value)} style={[s.filterChip, type === value && s.filterChipSelected]}><Text style={s.filterChipText}>{value}</Text></Pressable>)}</View>
              <Text style={s.filterLabel}>Sort</Text><View style={s.filterChips}>{(["recent", "city"] as const).map(value => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: sort === value }} onPress={() => setSort(value)} style={[s.filterChip, sort === value && s.filterChipSelected]}><Text style={s.filterChipText}>{value === "recent" ? "Recently saved" : "By destination"}</Text></Pressable>)}</View>
              <View style={[s.filterActions, fontScale > 1.3 && { flexDirection: "column" }]}><WWButton label="Reset filters" secondary onPress={clear} /><WWButton label={`Show ${visible.length} ${visible.length === 1 ? "place" : "places"}`} onPress={() => { setFilters(false); setCityQuery(""); list.current?.scrollToOffset({ offset: 0, animated: false }); }} /></View>
            </View>}
          </ScrollView>
        </View>
      </View>
    </Modal>
  </View>;
}

function PlaceRow({ item, onPress, onShowMap, onEdit, onRetry, hideCity = false, inbox = false, sharedPhoto = false, excerpt }: {
  item: DreamItem;
  onPress: () => void;
  onShowMap?: () => void;
  onEdit?: () => void; hideCity?: boolean; inbox?: boolean; sharedPhoto?: boolean;
  onRetry?: () => Promise<void>;
  excerpt?: string;
}) {
  const [retrying, setRetrying] = React.useState(false), [retryError, setRetryError] = React.useState(false);
  const retryLock = React.useRef(false), mounted = React.useRef(true);
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const state = dreamProcessingState(item);
  const title = dreamCardTitle(item);
  const point = exactMapPoint(item);
  const note = state?.label || (point ? undefined : locationNote(item));
  return (
    <View style={s.placePaper}>
      <Pressable onPress={onPress} accessibilityRole="button" accessibilityLabel={`Details for ${title}${excerpt ? `, ${excerpt}` : ""}`}
        accessibilityHint={state?.detail} style={s.place}>
        <View style={[s.thumbnail, sharedPhoto && s.sharedThumbnail]}>{sharedPhoto ? <PlaceSymbol category={item.category} size={25} /> : <DreamPhoto item={item} compact />}</View>
        <View style={s.placeCopy}>
          <Text style={s.placeTitle} numberOfLines={2}>{title}</Text>
          {excerpt ? <Text style={s.placeExcerpt} numberOfLines={2}>{excerpt}</Text> : null}
          <Text style={s.placeCity} numberOfLines={2}>{hideCity ? [dreamLocationType(item), item.regionOrNeighborhood].filter(Boolean).join(" · ") : dreamCardMeta(item)}</Text>
          {note && <Text style={[s.status, (state?.kind === "unreadable" || state?.kind === "failed") && s.statusError]} numberOfLines={2}>{note}</Text>}
        </View>
      </Pressable>
      {point && onShowMap && <Pressable accessibilityRole="button" accessibilityLabel={`Show ${title} on map`}
        accessibilityHint="Reveals this place on the country map" onPress={onShowMap} style={s.pinButton}>
        <WWIcon name="pin" size={19} color={colors.blue} />
      </Pressable>}
      {!inbox && !point && !isSavedInspiration(item) && onEdit && !["sorting", "upload", "deferred"].includes(state?.kind || "") && <Pressable accessibilityRole="button" accessibilityLabel={`Add location for ${title}`} onPress={onEdit} style={s.pinButton}><WWIcon name="plus" size={18} /></Pressable>}
      {inbox && state && <Text style={s.inboxReason}>{state.detail}</Text>}
      {inbox && needsDreamAttention(item) && <View style={s.inboxActions}>
        {onRetry && (item.uploadStatus === "failed" || state?.kind === "unreadable" || state?.kind === "failed") ? <WWButton label={retrying ? "Retrying…" : "Try again"} secondary disabled={retrying} onPress={async () => {
          if (retryLock.current) return;
          retryLock.current = true; setRetrying(true); setRetryError(false);
          try { await onRetry(); } catch { if (mounted.current) setRetryError(true); }
          finally { retryLock.current = false; if (mounted.current) setRetrying(false); }
        }} /> : onEdit && !item.uploadStatus ? <Pressable accessibilityRole="button" onPress={onEdit} style={s.metaAction}><Text style={s.actionText}>Add location</Text></Pressable> : null}
        <Pressable accessibilityRole="link" accessibilityLabel={`View original post for ${title}`} style={s.metaAction} onPress={() => { const url = safeWebUrl(item.sourceUrl); if (url) void Linking.openURL(url).catch(() => {}); }}><Text style={s.actionText}>View post ↗</Text></Pressable>
        {retryError && <Text accessibilityRole="alert" style={s.inboxReason}>Couldn’t retry yet. Your link is still saved.</Text>}
      </View>}
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
  onSave: (url: string, caption?: string) => boolean | Promise<boolean>;
  visible: boolean;
  onCloseRequestChange?: (handler: (() => void) | null) => void;
}) {
  const insets = useSafeAreaInsets(),
    [url, setUrl] = React.useState(""),
    [caption, setCaption] = React.useState(""),
    [showCaption, setShowCaption] = React.useState(false),
    [discarding, setDiscarding] = React.useState(false),
    [saving, setSaving] = React.useState(false),
    [error, setError] = React.useState<string>();
  const savingLock = React.useRef(false), mounted = React.useRef(true);
  React.useEffect(() => () => { mounted.current = false; }, []);
  const reducedMotion = useReducedMotion();
  const requestClose = () => {
    if (savingLock.current) return;
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
          title="Save from Instagram"
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
              setError(undefined);
            }}
            editable={!saving}
            placeholder="https://www.instagram.com/reel/…"
            placeholderTextColor={colors.mutedInk}
            accessibilityLabel="Instagram link"
            style={s.captureInput}
          />
          {error && (
            <Text accessibilityRole="alert" style={s.error}>
              {error}
            </Text>
          )}
          <View style={{ marginTop: 20 }}>
            <WWButton
              label={saving ? "Keeping post…" : "Save to Dreams"}
              disabled={!url.trim() || saving}
              onPress={async () => {
                if (savingLock.current) return;
                savingLock.current = true; setSaving(true); setError(undefined);
                try {
                  const kept = await onSave(url, caption);
                  if (!mounted.current) return;
                  if (kept) onClose();
                  else setError('Paste a valid Instagram post or reel link.');
                } catch (caught) {
                  if (mounted.current) setError(caught instanceof Error ? caught.message : 'This post could not be kept. Please try again.');
                } finally {
                  savingLock.current = false;
                  if (mounted.current) setSaving(false);
                }
              }}
            />
          </View>
          <Pressable accessibilityRole="button" accessibilityLabel="Optional original caption" accessibilityState={{ expanded: showCaption }} onPress={() => setShowCaption(!showCaption)} style={s.captionToggle}><Text style={s.actionText}>{showCaption ? "Hide caption" : "Add the original caption"}</Text><WWIcon name={showCaption ? "close" : "plus"} size={17} /></Pressable>
          {showCaption && <><Text style={s.inputLabel}>Original caption · optional</Text>
          <TextInput
            value={caption}
            onChangeText={setCaption}
            editable={!saving}
            multiline
            placeholder="Add the original caption to help identify the place"
            placeholderTextColor={colors.mutedInk}
            accessibilityLabel="Original caption"
            style={[s.captureInput, s.caption]}
          /></>}
        </ScrollView>}
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
  countryPhoto: { width: 54, height: 48, padding: 3, borderWidth: 1, borderColor: colors.paperBorder, backgroundColor: colors.paperPhoto, transform: [{ rotate: "-3deg" }] },
  sourceGroup: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10, minHeight: 44, marginHorizontal: 24, paddingTop: 8, borderTopWidth: 1, borderColor: colors.paperBorderSoft },
  sourceGroupText: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk },
  sharedThumbnail: { alignItems: "center", justifyContent: "center", backgroundColor: "transparent", borderLeftWidth: 1, borderColor: colors.paperBorderSoft },
  inspirationTitle: { fontFamily: fonts.display, fontSize: 20, color: colors.ink },
  savedReceipt: { position: "absolute", left: 24, right: 24, backgroundColor: colors.blue, borderRadius: 8, padding: 16 },
  savedReceiptText: { fontFamily: fonts.sansRegular, color: colors.paper, fontSize: 14, lineHeight: 20 },
  browseHeader: { paddingHorizontal: 24, paddingTop: 0, paddingBottom: 8 },
  backLink: { flexDirection: "row", alignItems: "center", gap: 7, minHeight: 44, alignSelf: "flex-start" },
  planTrip: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, minHeight: 52, paddingHorizontal: 18, paddingVertical: 12, marginTop: 16, marginBottom: 8, alignSelf: "stretch", backgroundColor: colors.ink, borderRadius: 4 },
  planTripText: { fontFamily: fonts.sansSemi, fontSize: 16, color: colors.paperSoft },
  backText: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 13 },
  browseTitleLine: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 0, marginBottom: 0 },
  browseTitle: { fontFamily: fonts.displayItalic, fontSize: 31, lineHeight: 36, color: colors.ink },
  browseSummary: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk, flexShrink: 1 },
  addButton: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.paperDeep, alignItems: "center", justifyContent: "center" },
  viewTabs: { flexDirection: "row", marginHorizontal: 24, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft, marginBottom: 12, gap: 24 },
  viewTab: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4, borderBottomWidth: 2, borderBottomColor: "transparent" },
  viewTabSelected: { borderBottomColor: colors.ink },
  viewTabText: { color: colors.mutedInk, fontFamily: fonts.sansRegular, fontSize: 14 },
  viewTabTextSelected: { color: colors.ink, fontFamily: fonts.sansSemi },
  searchLine: { flexDirection: "row", gap: 10, marginHorizontal: 24 },
  searchBox: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: 9, paddingHorizontal: 12, backgroundColor: colors.paperDeep, borderRadius: 5 },
  librarySearch: { flexDirection: "row", alignItems: "center", gap: 9, marginHorizontal: 24, marginBottom: 20, paddingHorizontal: 12, backgroundColor: colors.paperDeep, borderRadius: 5 },
  searchInput: { flex: 1, minWidth: 0, minHeight: 46, paddingVertical: 10, fontFamily: fonts.sansRegular, color: colors.ink, fontSize: 14 },
  filterButton: { width: 46, minHeight: 46, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 5, alignItems: "center", justifyContent: "center" },
  filterButtonActive: { backgroundColor: colors.paperDeep, borderColor: colors.blue },
  listMeta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginHorizontal: 24, marginVertical: 5, flexWrap: "wrap" },
  metaAction: { minHeight: 44, justifyContent: "center" },
  selectedPlace: { flexDirection: "row", marginHorizontal: 24, paddingVertical: 16, gap: 12, alignItems: "center", borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  filterOverlay: { flex: 1, backgroundColor: "rgba(20,39,45,.38)", justifyContent: "flex-end" },
  filterSheet: { backgroundColor: colors.paperSoft, borderTopLeftRadius: 18, borderTopRightRadius: 18, width: "100%", maxWidth: 600, alignSelf: "center" },
  filterSheetHeader: { flexDirection: "row", alignItems: "center", gap: 12, paddingLeft: 24, paddingRight: 12, paddingTop: 12 },
  filterSheetTitle: { flex: 1, fontFamily: fonts.display, fontSize: 27, color: colors.ink },
  filterPad: { paddingHorizontal: 24, paddingBottom: 16 },
  filterLabel: { fontFamily: fonts.sansSemi, color: colors.ink, fontSize: 14, marginTop: 22, marginBottom: 10 },
  filterChips: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  filterChip: { minHeight: 44, justifyContent: "center", borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 5, paddingHorizontal: 13, paddingVertical: 10 },
  filterChipSelected: { backgroundColor: colors.paperDeep, borderColor: colors.blue },
  filterChipText: { fontFamily: fonts.sansRegular, color: colors.ink, fontSize: 13 },
  filterActions: { flexDirection: "row", gap: 12, marginTop: 26, flexWrap: "wrap" },
  sourceKicker: { fontFamily: fonts.mono, fontSize: 10, letterSpacing: 1.4, color: colors.mutedInk, marginTop: 10 },
  sourceTitle: { fontSize: 30, lineHeight: 35 },
  organizing: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12, marginHorizontal: 24, minHeight: 44, marginBottom: 12 },
  inboxReason: { width: "100%", paddingBottom: 16, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk },
  inboxActions: { width: "100%", flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 14, paddingBottom: 20 },
  captionToggle: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 10, marginTop: 15 },
  countryScreen: { flex: 1, minHeight: 0 },
  countryContent: { flex: 1, minHeight: 0 },
  headerIcon: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  previewPhoto: { width: 50, height: 60, overflow: "hidden", backgroundColor: colors.paperDeep },
  previewTitle: { fontFamily: fonts.display, fontSize: 21, lineHeight: 25, color: colors.ink },
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
  inbox: { marginHorizontal: 24, marginTop: -8, marginBottom: 10, paddingVertical: 8, minHeight: 44,
    flexDirection: "row", alignItems: "center", gap: 12 },
  inboxTitle: { flex: 1, fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk },
  inboxCount: { fontFamily: fonts.sansSemi, fontSize: 12, color: colors.mutedInk },
  inboxSummary: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk, marginTop: 3 },
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
  placePaper: {
    marginHorizontal: 24,
    marginBottom: 0,
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    borderBottomWidth: 1,
    borderColor: colors.paperBorderSoft,
  },
  place: {
    flex: 1,
    paddingVertical: 12,
    paddingLeft: 0,
    paddingRight: 10,
    minHeight: 86,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  thumbnail: {
    width: 56,
    height: 64,
    borderRadius: 4,
    backgroundColor: colors.paperPhoto,
    overflow: "hidden",
  },
  pinButton: { width: 44, minHeight: 56, alignItems: "center", justifyContent: "center" },
  placeCopy: { flex: 1, minWidth: 0 },
  placeTitle: {
    fontFamily: fonts.display,
    fontSize: 21,
    lineHeight: 25,
    color: colors.ink,
    letterSpacing: -0.35,
    includeFontPadding: false,
  },
  placeExcerpt: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 13, lineHeight: 19, marginTop: 3 },
  placeCity: {
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    color: colors.mutedInk,
    marginTop: 6,
  },
  status: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk, marginTop: 4 },
  statusError: { color: colors.red },
  placeActions: { flexDirection: "row", flexWrap: "wrap", gap: 13, marginTop: 10 },
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
