import React from "react";
import {
  BackHandler,
  FlatList,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
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
import { PaperMap } from "../components/world-window/trips/PaperMap";
import type { MapPoint } from "../components/world-window/trips/tripPresentation";
import type { BottomNavTab } from "../data/trotterMock";
import { DreamItem, useDreams } from "../services/dreams";
import { colors, fonts, layout } from "../theme/trotterTheme";

export function DreamsScreen({
  active,
  onChange,
}: {
  active: BottomNavTab;
  onChange: (tab: BottomNavTab) => void;
}) {
  const insets = useSafeAreaInsets(),
    store = useDreams();
  const [country, setCountry] = React.useState<{
      key: string;
      title: string;
    }>(),
    [review, setReview] = React.useState(false),
    [capture, setCapture] = React.useState(false),
    [selectedId, setSelectedId] = React.useState<string>();
  const homeOffset = React.useRef(0),
    selected = store.items.find((item) => item.id === selectedId);
  const boards = React.useMemo(() => countryBoards(store.items), [store.items]);
  const points = React.useMemo(
    () =>
      store.items
        .map(exactMapPoint)
        .filter((point): point is MapPoint => Boolean(point)),
    [store.items],
  );
  const countryItems = React.useMemo(
    () =>
      store.items.filter((item) => countryKey(item.country) === country?.key),
    [store.items, country?.key],
  );
  const reviews = React.useMemo(
    () =>
      store.items.filter(
        (item) => item.needsReview || item.status === "failed",
      ),
    [store.items],
  );
  const back = () => {
    setCountry(undefined);
    setReview(false);
  };
  React.useEffect(() => {
    if (!country && !review) return;
    const handler = BackHandler.addEventListener("hardwareBackPress", () => {
      back();
      return true;
    });
    return () => handler.remove();
  }, [country, review]);
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
    <View style={s.screen}>
      {country || review ? (
        <CountryPlaces
          key={country?.key || "review"}
          title={review ? "To review" : country?.title || "Saved places"}
          items={review ? reviews : countryItems}
          review={review}
          topInset={insets.top}
          bottomInset={insets.bottom}
          loading={loading}
          error={store.error}
          onBack={back}
          onRefresh={() => void store.refresh()}
          onSelect={setSelectedId}
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
            paddingTop: insets.top,
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
              onPress={() => setCountry({ key: item.key, title: item.title })}
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
          item={selected}
          points={points.filter(
            (point) =>
              countryKey(
                store.items.find((item) => item.id === point.id)?.country,
              ) === countryKey(selected.country),
          )}
          onClose={() => setSelectedId(undefined)}
          onSave={store.updateItem}
          onDelete={store.deleteItem}
          onRetry={() =>
            store.shareInstagramLink(selected.sourceUrl, selected.caption)
          }
        />
      )}
      {capture && (
        <CapturePlace
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
  title,
  items,
  review,
  topInset,
  bottomInset,
  loading,
  error,
  onBack,
  onRefresh,
  onSelect,
}: {
  title: string;
  items: DreamItem[];
  review: boolean;
  topInset: number;
  bottomInset: number;
  loading: boolean;
  error?: string;
  onBack: () => void;
  onRefresh: () => void;
  onSelect: (id: string) => void;
}) {
  const [query, setQuery] = React.useState(""),
    [city, setCity] = React.useState(""),
    [category, setCategory] = React.useState<DreamFilter>("All"),
    [searching, setSearching] = React.useState(false),
    [opened, setOpened] = React.useState<string>(),
    [selected, setSelected] = React.useState<string>();
  const list = React.useRef<FlatList<DreamItem>>(null);
  const mapOffset = React.useRef(0);
  const cities = React.useMemo(() => cityNames(items), [items]),
    visible = React.useMemo(
      () =>
        filterDreams(items, query, city, category).sort(
          (a, b) =>
            (a.city || "").localeCompare(b.city || "") ||
            (a.placeName || "").localeCompare(b.placeName || ""),
        ),
      [items, query, city, category],
    );
  const points = React.useMemo(
    () =>
      visible
        .map(exactMapPoint)
        .filter((point): point is MapPoint => Boolean(point)),
    [visible],
  );
  React.useEffect(() => {
    if (city && !cities.includes(city)) setCity("");
  }, [city, cities]);
  return (
    <FlatList
      ref={list}
      data={visible}
      keyExtractor={(item) => item.id}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode="on-drag"
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        paddingTop: topInset,
        paddingBottom: bottomInset + layout.bottomNavHeight + 24,
      }}
      initialNumToRender={8}
      windowSize={7}
      refreshControl={
        <RefreshControl
          refreshing={loading}
          onRefresh={onRefresh}
          tintColor={colors.blue}
        />
      }
      ListHeaderComponent={
        <>
          <WWHeader
            title="Dreams"
            onBack={onBack}
            action={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={
                  searching ? "Close search" : "Search saved places"
                }
                onPress={() => {
                  setSearching(!searching);
                  setQuery("");
                }}
                style={s.icon}
              >
                <WWIcon name={searching ? "close" : "search"} size={20} />
              </Pressable>
            }
          />
          <View style={s.countryMeta}>
            <View pointerEvents="none" style={StyleSheet.absoluteFill}>
              {Array.from({ length: 6 }, (_, i) => (
                <View
                  key={i}
                  style={{
                    position: "absolute",
                    left: 0,
                    right: 0,
                    top: 30 + i * 31,
                    height: 1,
                    backgroundColor: "#f2f0e4",
                  }}
                />
              ))}
            </View>
            <Text style={s.countryTitle}>{title}</Text>
            <Text style={s.meta}>
              {items.length} saved {items.length === 1 ? "place" : "places"}
              {cities.length
                ? ` · ${cities.length} ${cities.length === 1 ? "city" : "cities"}`
                : ""}
            </Text>
          </View>
          {!review && (
            <View
              style={s.mapPaper}
              onLayout={(event) => {
                mapOffset.current = event.nativeEvent.layout.y;
              }}
            >
              <PaperMap
                points={points}
                fitKey={`${title}-${city}-${category}`}
                height={248}
                selectedId={selected}
                onSelect={(id) => {
                  setSelected(id);
                }}
              />
              <View style={s.mapFoot}>
                <Text style={s.mapCount}>{points.length} on map</Text>
                {points.length < visible.length && (
                  <Text style={s.mapNote}>
                    {visible.length - points.length}{" "}
                    {visible.length - points.length === 1
                      ? "place needs"
                      : "places need"}{" "}
                    a pin
                  </Text>
                )}
              </View>
              {selected && visible.find((item) => item.id === selected) && (
                <Pressable
                  style={s.mapSelection}
                  onPress={() => {
                    setOpened(selected);
                    const index = visible.findIndex(
                      (item) => item.id === selected,
                    );
                    if (index >= 0)
                      list.current?.scrollToIndex({
                        index,
                        animated: true,
                        viewPosition: 0.12,
                      });
                  }}
                >
                  <Text style={s.mapSelectionTitle}>
                    {visible.find((item) => item.id === selected)?.placeName ||
                      "Saved place"}
                  </Text>
                  <WWIcon name="arrow" size={17} />
                </Pressable>
              )}
            </View>
          )}
          {searching && (
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search saved places"
              accessibilityLabel="Search saved places"
              placeholderTextColor={colors.mutedInk}
              style={s.search}
            />
          )}
          {cities.length > 1 && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={s.cityFilters}
            >
              {["", ...cities].map((value) => (
                <Pressable
                  key={value || "all"}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: city === value }}
                  onPress={() => setCity(value)}
                  style={[s.city, city === value && s.cityActive]}
                >
                  <Text
                    style={[s.cityText, city === value && s.cityTextActive]}
                  >
                    {value || "All cities"}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          )}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={s.categories}
          >
            {dreamCategories
              .filter(
                (value) =>
                  value === "All" ||
                  filterDreams(items, "", "", value).length > 0,
              )
              .map((value) => (
                <Pressable
                  key={value}
                  accessibilityRole="tab"
                  accessibilityState={{ selected: category === value }}
                  onPress={() => setCategory(value)}
                  style={[s.category, category === value && s.categoryActive]}
                >
                  <Text
                    style={[
                      s.categoryText,
                      category === value && s.categoryTextActive,
                    ]}
                  >
                    {value}{" "}
                    <Text style={s.filterCount}>
                      {filterDreams(items, query, city, value).length}
                    </Text>
                  </Text>
                </Pressable>
              ))}
          </ScrollView>
          {error && <ErrorLine error={error} onRetry={onRefresh} />}
        </>
      }
      onScrollToIndexFailed={({ index, averageItemLength }) =>
        list.current?.scrollToOffset({
          offset: mapOffset.current + 248 + averageItemLength * index,
          animated: true,
        })
      }
      renderItem={({ item, index }) => (
        <View>
          {(index === 0 || item.city !== visible[index - 1].city) && (
            <View style={s.cityDivider}>
              <Text style={s.cityHeading}>{item.city || "Saved places"}</Text>
              <View style={s.cityRule} />
              <Text style={s.cityCount}>
                {visible.filter((place) => place.city === item.city).length}
              </Text>
            </View>
          )}
          <PlaceRow
            item={item}
            expanded={opened === item.id}
            onPress={() => {
              setOpened(opened === item.id ? undefined : item.id);
              setSelected(item.id);
            }}
            onEdit={() => onSelect(item.id)}
            onShowMap={() => {
              if (!exactMapPoint(item)) {
                onSelect(item.id);
                return;
              }
              setSelected(item.id);
              list.current?.scrollToOffset({
                offset: mapOffset.current,
                animated: true,
              });
            }}
          />
        </View>
      )}
      ListEmptyComponent={
        <WWEmpty
          title={
            items.length
              ? "No matching places"
              : review
                ? "All caught up"
                : "No saved places here"
          }
          body={
            items.length ? "Try another category, city or search." : undefined
          }
        />
      }
    />
  );
}
function PlaceRow({
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
            !exactMapPoint(item) && <Text style={s.pinNote}>Add map pin</Text>
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
          {item.summary ? (
            <Text style={s.placeSummary}>{item.summary}</Text>
          ) : null}
          {item.regionOrNeighborhood ? (
            <View style={s.addressLine}>
              <WWIcon name="pin" size={15} />
              <Text style={s.addressText}>
                {[item.regionOrNeighborhood, item.city]
                  .filter(Boolean)
                  .join(", ")}
              </Text>
            </View>
          ) : null}
          <View style={s.placeActions}>
            <Pressable onPress={onShowMap} style={s.placeAction}>
              <Text style={s.actionText}>
                {exactMapPoint(item) ? "Show on map" : "Add map pin"}
              </Text>
            </Pressable>
            {safeWebUrl(item.sourceUrl) && (
              <Pressable
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
            <Pressable onPress={onEdit} style={s.placeAction}>
              <Text style={s.actionText}>Edit</Text>
            </Pressable>
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
}: {
  onClose: () => void;
  onSave: (url: string, caption?: string) => boolean;
}) {
  const insets = useSafeAreaInsets(),
    [url, setUrl] = React.useState(""),
    [caption, setCaption] = React.useState(""),
    [error, setError] = React.useState(false);
  return (
    <Modal
      visible
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
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
              onPress={onClose}
              style={s.icon}
            >
              <WWIcon name="close" />
            </Pressable>
          }
        />
        <ScrollView
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
        </ScrollView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const s = StyleSheet.create({
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
    backgroundColor: "#fffdf5",
    overflow: "hidden",
  },
  countryTitle: {
    fontFamily: fonts.display,
    fontStyle: "italic",
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
    backgroundColor: "#fcfaf3",
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
  cityFilters: { paddingHorizontal: 24, gap: 7, paddingBottom: 12 },
  city: {
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
  categories: { paddingHorizontal: 24, gap: 7, marginBottom: 16 },
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
    fontFamily: fonts.display,
    fontStyle: "italic",
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
    backgroundColor: "#fffdf5",
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
    backgroundColor: "#fffdf5",
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
