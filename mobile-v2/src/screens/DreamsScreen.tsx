import React from 'react';
import {
  Image,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav, IconButton, IconGlyph, PaperSurface, ScreenHeader } from '../components/trotter/TrotterKit';
import { BottomNavTab } from '../data/trotterMock';
import { Dream, DreamItem, DreamItemCategory, useDreams } from '../services/dreams';
import { getApiBaseUrl, getStoredToken } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';

type DreamsView =
  | { name: 'home' }
  | { name: 'detail'; dreamId: string }
  | { name: 'review' };

const CATEGORY_OPTIONS: DreamItemCategory[] = [
  'restaurant',
  'cafe',
  'bar',
  'hotel',
  'attraction',
  'activity',
  'beach',
  'shopping',
  'nature',
  'museum',
  'event',
  'unknown',
];

const COVER_IMAGES: Record<string, number> = {
  France: require('../../assets/country-icons/17_france_eiffel-tower.png'),
  Greece: require('../../assets/country-icons/21_greece_parthenon.png'),
  Iceland: require('../../assets/country-icons/14_iceland_northern-lights.png'),
  Italy: require('../../assets/country-icons/20_italy_colosseum.png'),
  Japan: require('../../assets/country-icons/56_japan_mount-fuji.png'),
  Malaysia: require('../../assets/country-icons/52_malaysia_petronas-towers.png'),
  Mexico: require('../../assets/country-icons/03_mexico_chichen-itza.png'),
  Morocco: require('../../assets/country-icons/35_morocco_hassan_ii_mosque.png'),
  Portugal: require('../../assets/country-icons/19_portugal_belem-tower.png'),
  Spain: require('../../assets/country-icons/18_spain_sagrada-familia.png'),
  Thailand: require('../../assets/country-icons/48_thailand_wat_arun.png'),
  'United States': require('../../assets/country-icons/01_united-states_golden-gate-bridge.png'),
};

const fallbackCoverImage = require('../../assets/objects/globe.png');

export function DreamsScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const dreamsStore = useDreams();
  const [view, setView] = React.useState<DreamsView>({ name: 'home' });
  const selectedDream = view.name === 'detail' ? dreamsStore.dreams.find((dream) => dream.id === view.dreamId) : undefined;
  const selectedItems = selectedDream ? dreamsStore.items.filter((item) => item.dreamId === selectedDream.id) : [];

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}
      >
        <ScreenHeader
          title={view.name === 'home' ? 'DREAMS' : view.name === 'review' ? 'REVIEW' : 'DREAM'}
          subtitle={view.name === 'home' ? 'SAVED INSPIRATION' : view.name === 'review' ? 'NEEDS REVIEW' : selectedDream?.title.toUpperCase()}
          leftAction={
            view.name === 'home'
              ? <IconButton variant="paper" shape="circle" icon={<IconGlyph name="tag" color={colors.ink} size={22} />} />
              : <BackButton onPress={() => setView({ name: 'home' })} />
          }
          rightActions={[
            <IconButton key="refresh" variant="paper" shape="circle" onPress={() => dreamsStore.refresh()} icon={<Text allowFontScaling={false} style={styles.refreshIcon}>R</Text>} />,
          ]}
        />

        {view.name === 'home' ? (
          <>
            <PasteInstagramCard
              screenPadding={screenPadding}
              contentWidth={contentWidth}
              onSave={(url, caption) => {
                dreamsStore.shareInstagramLink(url, caption);
                setView({ name: 'home' });
              }}
            />
            <ProcessingPanel
              items={dreamsStore.processingItems}
              status={dreamsStore.status}
              error={dreamsStore.error}
              screenPadding={screenPadding}
              contentWidth={contentWidth}
            />
            <DreamsHome
              dreams={dreamsStore.dreams}
              status={dreamsStore.status}
              screenPadding={screenPadding}
              contentWidth={contentWidth}
              onOpenDream={(dream) => setView({ name: 'detail', dreamId: dream.id })}
            />
          </>
        ) : null}

        {view.name === 'detail' && selectedDream ? (
          <DreamDetail
            dream={selectedDream}
            items={selectedItems}
            screenPadding={screenPadding}
            contentWidth={contentWidth}
            onConfirm={dreamsStore.confirmItem}
            onDelete={dreamsStore.deleteItem}
            onUpdate={dreamsStore.updateItem}
          />
        ) : null}

        {view.name === 'review' ? (
          <ReviewInbox
            items={dreamsStore.needsReviewItems}
            screenPadding={screenPadding}
            contentWidth={contentWidth}
            onConfirm={dreamsStore.confirmItem}
            onDelete={dreamsStore.deleteItem}
            onUpdate={dreamsStore.updateItem}
          />
        ) : null}
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function PasteInstagramCard({
  screenPadding,
  contentWidth,
  onSave,
}: {
  screenPadding: number;
  contentWidth: number;
  onSave: (url: string, caption?: string) => void;
}) {
  const [url, setUrl] = React.useState('');
  const [caption, setCaption] = React.useState('');
  const [showCaption, setShowCaption] = React.useState(false);
  const canSave = url.trim().length > 0;

  return (
    <PaperSurface radius={14} padding={spacing.md} style={[styles.pasteCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
      <View style={styles.panelHeader}>
        <View>
          <Text allowFontScaling={false} style={styles.panelTitle}>DEV LINK TESTER</Text>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.panelSub}>Production capture uses Instagram Share to Trotter.</Text>
        </View>
        <IconGlyph name="tag" color={colors.red} size={25} />
      </View>
      <TextInput
        value={url}
        onChangeText={setUrl}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder="instagram.com/reel/..."
        placeholderTextColor={colors.mutedInk}
        style={styles.input}
      />
      {showCaption ? (
        <TextInput
          value={caption}
          onChangeText={setCaption}
          multiline
          placeholder="Optional caption for parser testing"
          placeholderTextColor={colors.mutedInk}
          style={[styles.input, styles.captionInput]}
        />
      ) : null}
      <View style={styles.actionRow}>
        <Pressable onPress={() => setShowCaption((current) => !current)} style={styles.secondaryButton}>
          <Text allowFontScaling={false} style={styles.secondaryButtonText}>{showCaption ? 'HIDE CAPTION' : 'ADD CAPTION'}</Text>
        </Pressable>
        <Pressable
          disabled={!canSave}
          onPress={() => {
            onSave(url, caption);
            setUrl('');
            setCaption('');
          }}
          style={[styles.primaryButton, !canSave && styles.disabledButton]}
        >
          <Text allowFontScaling={false} style={styles.primaryButtonText}>SAVE</Text>
        </Pressable>
      </View>
    </PaperSurface>
  );
}

function DreamsHome({
  dreams,
  status,
  screenPadding,
  contentWidth,
  onOpenDream,
}: {
  dreams: Dream[];
  status: 'idle' | 'loading' | 'refreshing' | 'error';
  screenPadding: number;
  contentWidth: number;
  onOpenDream: (dream: Dream) => void;
}) {
  const isLoading = status === 'loading' || status === 'refreshing';
  return (
    <View style={{ marginHorizontal: screenPadding, width: contentWidth, marginTop: spacing.lg }}>
      <Text allowFontScaling={false} style={styles.sectionTitle}>DESTINATIONS</Text>
      {dreams.length === 0 && isLoading ? (
        <PaperSurface radius={12} padding={spacing.lg} style={styles.emptyDreamsPanel}>
          <Text allowFontScaling={false} style={styles.emptyDreamsTitle}>LOADING DREAMS</Text>
          <Text maxFontSizeMultiplier={1.05} style={styles.emptyDreamsSub}>Pulling your saved travel ideas from Trotter.</Text>
        </PaperSurface>
      ) : dreams.length === 0 ? (
        <PaperSurface radius={12} padding={spacing.lg} style={styles.emptyDreamsPanel}>
          <Text allowFontScaling={false} style={styles.emptyDreamsTitle}>NO DREAMS YET</Text>
          <Text maxFontSizeMultiplier={1.05} style={styles.emptyDreamsSub}>Share or paste an Instagram travel post to start building your saved ideas.</Text>
        </PaperSurface>
      ) : (
        <View style={styles.dreamGrid}>
          {dreams.map((dream) => (
            <DreamCard key={dream.id} dream={dream} onPress={() => onOpenDream(dream)} />
          ))}
        </View>
      )}
    </View>
  );
}

function ProcessingPanel({
  items,
  status,
  error,
  screenPadding,
  contentWidth,
}: {
  items: DreamItem[];
  status: 'idle' | 'loading' | 'refreshing' | 'error';
  error?: string;
  screenPadding: number;
  contentWidth: number;
}) {
  const isRefreshing = status === 'loading' || status === 'refreshing';
  if (items.length === 0 && !isRefreshing && !error) return null;

  const title = items.length > 1 ? `${items.length} ideas processing` : items.length === 1 ? '1 idea processing' : isRefreshing ? 'Refreshing Dreams' : 'Dreams needs attention';
  const subtitle = error
    ? error
    : items.length > 0
      ? 'Fetching caption metadata, parsing the place, and attaching a Maps link.'
      : 'Checking the latest saved ideas from the backend.';

  return (
    <PaperSurface radius={12} padding={spacing.md} style={[styles.processingPanel, { marginHorizontal: screenPadding, width: contentWidth }]}>
      <View style={styles.processingTop}>
        <View style={styles.processingPulse}>
          <View style={styles.processingDot} />
        </View>
        <View style={styles.processingCopy}>
          <Text allowFontScaling={false} numberOfLines={1} style={styles.processingTitle}>{title.toUpperCase()}</Text>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={2} style={styles.processingSub}>{subtitle}</Text>
        </View>
      </View>
      {items.length > 0 ? (
        <View style={styles.processingList}>
          {items.slice(0, 3).map((item) => (
            <Text key={item.id} maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.processingItem}>
              {item.sourceUrl.replace(/^https?:\/\/(www\.)?/i, '')}
            </Text>
          ))}
        </View>
      ) : null}
    </PaperSurface>
  );
}

function DreamCard({ dream, onPress }: { dream: Dream; onPress: () => void }) {
  const visual = dreamVisual(dream.country, dream.city, dream.title);
  const destinationLine = [dream.city, dream.region, dream.country].filter(Boolean).join(', ') || 'Saved inspiration';
  return (
    <Pressable onPress={onPress} style={styles.dreamCardWrap}>
      <PaperSurface radius={10} padding={0} style={styles.dreamCard}>
        <View style={styles.dreamPhotoWrap}>
          <Image source={visual.image} resizeMode="cover" style={styles.dreamPhoto} />
          <View style={[styles.photoWash, { backgroundColor: visual.tint }]} />
        </View>
        <View style={styles.dreamCardBody}>
          <View style={styles.dreamCardTop}>
            <View style={styles.dreamCardCopy}>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.dreamTitle}>{dream.title}</Text>
              <Text allowFontScaling={false} numberOfLines={1} style={styles.dreamMeta}>{destinationLine}</Text>
            </View>
            <Text allowFontScaling={false} style={styles.cardMenu}>...</Text>
          </View>
          <View style={styles.dreamBottomRow}>
            <Text allowFontScaling={false} numberOfLines={1} style={styles.ideaCount}>{dream.itemCount} {dream.itemCount === 1 ? 'idea' : 'ideas'}</Text>
            {dream.processingCount > 0 ? <StatusBadge label="processing" tone="processing" /> : null}
          </View>
        </View>
      </PaperSurface>
    </Pressable>
  );
}

function DreamDetail({
  dream,
  items,
  screenPadding,
  contentWidth,
  onConfirm,
  onDelete,
  onUpdate,
}: {
  dream: Dream;
  items: DreamItem[];
  screenPadding: number;
  contentWidth: number;
  onConfirm: (id: string) => void;
  onDelete: (id: string) => void;
  onUpdate: (id: string, patch: Partial<DreamItem>) => void;
}) {
  return (
    <View style={{ marginHorizontal: screenPadding, width: contentWidth }}>
      <PaperSurface radius={14} padding={spacing.md} style={styles.detailSummary}>
        <Text allowFontScaling={false} style={styles.panelTitle}>{dream.title.toUpperCase()}</Text>
        <Text maxFontSizeMultiplier={1.05} style={styles.panelSub}>{dream.itemCount} saved ideas</Text>
      </PaperSurface>
      <View style={styles.itemList}>
        {items.map((item) => (
          <DreamItemCard key={item.id} item={item} onConfirm={onConfirm} onDelete={onDelete} onUpdate={onUpdate} />
        ))}
      </View>
    </View>
  );
}

function ReviewInbox({
  items,
  screenPadding,
  contentWidth,
  onConfirm,
  onDelete,
  onUpdate,
}: {
  items: DreamItem[];
  screenPadding: number;
  contentWidth: number;
  onConfirm: (id: string) => void;
  onDelete: (id: string) => void;
  onUpdate: (id: string, patch: Partial<DreamItem>) => void;
}) {
  return (
    <View style={{ marginHorizontal: screenPadding, width: contentWidth }}>
      {items.length === 0 ? (
        <PaperSurface radius={14} padding={spacing.lg} style={styles.emptyPanel}>
          <Text allowFontScaling={false} style={styles.panelTitle}>ALL CLEAR</Text>
          <Text maxFontSizeMultiplier={1.05} style={styles.panelSub}>Saved ideas that need review will show up here.</Text>
        </PaperSurface>
      ) : (
        <View style={styles.itemList}>
          {items.map((item) => (
            <DreamItemCard key={item.id} item={item} reviewMode onConfirm={onConfirm} onDelete={onDelete} onUpdate={onUpdate} />
          ))}
        </View>
      )}
    </View>
  );
}

function DreamItemCard({
  item,
  onConfirm,
  onDelete,
  onUpdate,
  reviewMode,
}: {
  item: DreamItem;
  onConfirm: (id: string) => void;
  onDelete: (id: string) => void;
  onUpdate: (id: string, patch: Partial<DreamItem>) => void;
  reviewMode?: boolean;
}) {
  const [editing, setEditing] = React.useState(false);
  const visual = dreamVisual(item.country, item.city, item.placeName || item.country || item.city, item.thumbnailUrl);

  return (
    <PaperSurface radius={10} padding={0} style={styles.itemCard}>
      <View style={styles.itemCardInner}>
        <View style={styles.itemPhotoWrap}>
          <Image source={visual.image} resizeMode="cover" style={styles.itemPhoto} />
          <View style={[styles.itemPhotoTint, { backgroundColor: visual.tint }]} />
        </View>
        <View style={styles.itemCopy}>
          <View style={styles.itemTop}>
            <View style={styles.itemTitleBlock}>
              <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.itemTitle}>
                {item.placeName || item.city || item.country || 'Instagram idea'}
              </Text>
              <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.itemLocation}>{[item.city, item.country].filter(Boolean).join(', ') || 'Unsorted'}</Text>
            </View>
            {item.status === 'processing' ? <StatusBadge label="processing" tone="processing" /> : null}
            {item.status === 'failed' ? <StatusBadge label="failed" tone="failed" /> : null}
          </View>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={3} style={styles.itemSummary}>{item.summary}</Text>
          <View style={styles.itemMetaRow}>
            <Text allowFontScaling={false} numberOfLines={1} style={styles.categoryChip}>{item.category.toUpperCase()}</Text>
          </View>
        </View>
      </View>
      {editing || reviewMode ? (
        <View style={styles.itemEditorWrap}>
          <DreamItemEditor item={item} onUpdate={onUpdate} onDone={() => setEditing(false)} />
        </View>
      ) : null}
      <View style={styles.itemActions}>
        <Pressable onPress={() => Linking.openURL(item.sourceUrl).catch(() => undefined)} style={styles.textButton}>
          <Text allowFontScaling={false} style={styles.textButtonText}>SOURCE</Text>
        </Pressable>
        <Pressable onPress={() => setEditing((current) => !current)} style={styles.textButton}>
          <Text allowFontScaling={false} style={styles.textButtonText}>{editing ? 'CLOSE' : 'EDIT'}</Text>
        </Pressable>
        {item.googleMapsUrl ? (
          <Pressable onPress={() => Linking.openURL(item.googleMapsUrl as string).catch(() => undefined)} style={styles.confirmButton}>
            <Text allowFontScaling={false} style={styles.confirmButtonText}>MAPS</Text>
          </Pressable>
        ) : null}
        <Pressable onPress={() => onDelete(item.id)} style={styles.deleteButton}>
          <Text allowFontScaling={false} style={styles.deleteButtonText}>DELETE</Text>
        </Pressable>
      </View>
    </PaperSurface>
  );
}

function BackButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={styles.backButton}>
      <Text allowFontScaling={false} style={styles.backArrow}>‹</Text>
    </Pressable>
  );
}

function dreamVisual(country?: string, city?: string, title?: string, thumbnailUrl?: string) {
  const image = thumbnailUrl
    ? {
        uri: thumbnailUrl.startsWith('http') ? thumbnailUrl : `${getApiBaseUrl()}${thumbnailUrl}`,
        headers: {
          ...(getStoredToken() ? { Authorization: `Bearer ${getStoredToken()}` } : {}),
          'ngrok-skip-browser-warning': 'true',
        },
      }
    : (country && COVER_IMAGES[country]) || fallbackCoverImage;
  const key = (country || city || title || '').toLowerCase();
  const accent = key.includes('japan') ? colors.red : key.includes('mexico') ? colors.green : key.includes('guatemala') ? colors.teal : key.includes('portugal') ? colors.blue : colors.brass;
  const tint = key.includes('guatemala') ? 'rgba(79,135,128,0.18)' : key.includes('japan') ? 'rgba(182,84,63,0.15)' : 'rgba(21,20,18,0.08)';
  return { image, accent, tint };
}

function DreamItemEditor({
  item,
  onUpdate,
  onDone,
}: {
  item: DreamItem;
  onUpdate: (id: string, patch: Partial<DreamItem>) => void;
  onDone: () => void;
}) {
  const [placeName, setPlaceName] = React.useState(item.placeName ?? '');
  const [city, setCity] = React.useState(item.city ?? '');
  const [country, setCountry] = React.useState(item.country ?? '');
  const [summary, setSummary] = React.useState(item.summary);
  const [category, setCategory] = React.useState<DreamItemCategory>(item.category);

  return (
    <View style={styles.editor}>
      <TextInput value={placeName} onChangeText={setPlaceName} placeholder="Place name" placeholderTextColor={colors.mutedInk} style={styles.editorInput} />
      <View style={styles.editorRow}>
        <TextInput value={city} onChangeText={setCity} placeholder="City" placeholderTextColor={colors.mutedInk} style={[styles.editorInput, styles.editorHalf]} />
        <TextInput value={country} onChangeText={setCountry} placeholder="Country" placeholderTextColor={colors.mutedInk} style={[styles.editorInput, styles.editorHalf]} />
      </View>
      <TextInput value={summary} onChangeText={setSummary} multiline placeholder="Summary" placeholderTextColor={colors.mutedInk} style={[styles.editorInput, styles.editorSummary]} />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.categoryScroller}>
        {CATEGORY_OPTIONS.map((option) => (
          <Pressable key={option} onPress={() => setCategory(option)} style={[styles.categoryOption, category === option && styles.categoryOptionActive]}>
            <Text allowFontScaling={false} style={[styles.categoryOptionText, category === option && styles.categoryOptionTextActive]}>{option}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <Pressable
        onPress={() => {
          onUpdate(item.id, {
            placeName: placeName.trim() || undefined,
            city: city.trim() || undefined,
            country: country.trim() || undefined,
            summary: summary.trim() || item.summary,
            category,
            needsReview: !(placeName.trim() && (city.trim() || country.trim())),
            status: placeName.trim() && (city.trim() || country.trim()) ? 'parsed' : 'needs_review',
          });
          onDone();
        }}
        style={styles.editorSave}
      >
        <Text allowFontScaling={false} style={styles.editorSaveText}>SAVE EDITS</Text>
      </Pressable>
    </View>
  );
}

function StatusBadge({ label, tone }: { label: string; tone: 'review' | 'confirmed' | 'processing' | 'failed' }) {
  const color = tone === 'review' || tone === 'failed' ? colors.red : tone === 'confirmed' ? colors.green : colors.mustard;
  return (
    <View style={[styles.statusBadge, { borderColor: color }]}>
      <Text allowFontScaling={false} numberOfLines={1} style={[styles.statusBadgeText, { color }]}>{label.toUpperCase()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  backButton: {
    width: 50,
    height: 50,
    borderRadius: 25,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
  },
  backArrow: {
    color: colors.brassSoft,
    fontFamily: fonts.sansBold,
    fontSize: 34,
    lineHeight: 38,
    marginTop: -2,
  },
  refreshIcon: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 22,
  },
  pasteCard: {
    marginTop: spacing.sm,
    opacity: 0.92,
  },
  processingPanel: {
    marginTop: spacing.md,
    gap: spacing.sm,
    borderColor: colors.mustard,
  },
  processingTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  processingPulse: {
    width: 30,
    height: 30,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: colors.mustard,
    alignItems: 'center',
    justifyContent: 'center',
  },
  processingDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.mustard,
  },
  processingCopy: {
    flex: 1,
    minWidth: 0,
  },
  processingTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1,
  },
  processingSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 16,
    marginTop: 2,
  },
  processingList: {
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
    paddingTop: spacing.sm,
    gap: 4,
  },
  processingItem: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  panelHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  panelTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1,
  },
  panelSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 3,
  },
  input: {
    minHeight: 44,
    marginTop: spacing.md,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperSoft,
    color: colors.ink,
    fontFamily: fonts.sansRegular,
    fontSize: 14,
    paddingHorizontal: spacing.md,
  },
  captionInput: {
    minHeight: 78,
    paddingTop: spacing.sm,
    textAlignVertical: 'top',
  },
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  primaryButton: {
    minHeight: 40,
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    backgroundColor: colors.dashboard,
  },
  disabledButton: {
    opacity: 0.45,
  },
  primaryButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  secondaryButton: {
    minHeight: 40,
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  secondaryButtonText: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
  },
  reviewCallout: {
    minHeight: 78,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.red,
    backgroundColor: colors.paper,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  reviewCalloutTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  reviewCalloutSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 3,
  },
  reviewCalloutCount: {
    color: colors.red,
    fontFamily: fonts.display,
    fontSize: 36,
  },
  sectionTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    letterSpacing: 1,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  dreamGrid: {
    gap: spacing.md,
  },
  emptyDreamsPanel: {
    minHeight: 110,
    justifyContent: 'center',
  },
  emptyDreamsTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    letterSpacing: 1,
  },
  emptyDreamsSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 5,
  },
  dreamCardWrap: {
    width: '100%',
    minWidth: 0,
  },
  dreamCard: {
    minHeight: 148,
    flexDirection: 'row',
    overflow: 'hidden',
  },
  dreamPhotoWrap: {
    width: 122,
    minHeight: 148,
    backgroundColor: colors.paperDeep,
    borderRightWidth: 1,
    borderRightColor: colors.paperBorder,
    overflow: 'hidden',
  },
  dreamPhoto: {
    width: '100%',
    height: '100%',
    position: 'absolute',
  },
  photoWash: {
    ...StyleSheet.absoluteFillObject,
  },
  dreamCardBody: {
    flex: 1,
    minWidth: 0,
    padding: spacing.md,
    justifyContent: 'space-between',
  },
  dreamCardTop: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  dreamCardCopy: {
    flex: 1,
    minWidth: 0,
  },
  dreamTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 29,
    lineHeight: 32,
  },
  dreamMeta: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    marginTop: 3,
  },
  cardMenu: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 18,
    lineHeight: 18,
  },
  dreamBottomRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  ideaCount: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  badgeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    marginTop: spacing.md,
    marginLeft: 4,
  },
  detailSummary: {
    marginTop: spacing.sm,
  },
  itemList: {
    gap: spacing.md,
    marginTop: spacing.md,
  },
  itemCard: {
    overflow: 'hidden',
  },
  itemCardInner: {
    flexDirection: 'row',
    minHeight: 148,
  },
  itemPhotoWrap: {
    width: 116,
    backgroundColor: colors.paperDeep,
    borderRightWidth: 1,
    borderRightColor: colors.paperBorder,
    overflow: 'hidden',
  },
  itemPhoto: {
    width: '100%',
    height: '100%',
    position: 'absolute',
  },
  itemPhotoTint: {
    ...StyleSheet.absoluteFillObject,
  },
  itemCopy: {
    flex: 1,
    minWidth: 0,
    padding: spacing.md,
  },
  itemTop: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  itemTitleBlock: {
    flex: 1,
    minWidth: 0,
  },
  itemTitle: {
    color: colors.ink,
    fontFamily: fonts.display,
    fontSize: 25,
    lineHeight: 28,
  },
  itemSummary: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    lineHeight: 18,
    marginTop: spacing.sm,
  },
  itemMetaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  categoryChip: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 10,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    borderRadius: 6,
    paddingHorizontal: 7,
    paddingVertical: 4,
  },
  itemLocation: {
    flex: 1,
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 12,
    marginTop: 2,
  },
  itemActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
    padding: spacing.sm,
    paddingTop: spacing.sm,
  },
  itemEditorWrap: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
  },
  textButton: {
    borderRadius: 7,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  textButtonText: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  confirmButton: {
    borderRadius: 7,
    backgroundColor: colors.green,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  confirmButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  deleteButton: {
    borderRadius: 7,
    backgroundColor: colors.red,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  deleteButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  statusBadge: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  statusBadgeText: {
    fontFamily: fonts.sansBold,
    fontSize: 9,
  },
  editor: {
    borderTopWidth: 1,
    borderTopColor: colors.paperBorder,
    paddingTop: spacing.sm,
    gap: spacing.sm,
  },
  editorRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  editorInput: {
    minHeight: 40,
    borderRadius: 7,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    backgroundColor: colors.paperSoft,
    color: colors.ink,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    paddingHorizontal: spacing.sm,
  },
  editorHalf: {
    flex: 1,
  },
  editorSummary: {
    minHeight: 68,
    paddingTop: spacing.sm,
    textAlignVertical: 'top',
  },
  categoryScroller: {
    flexGrow: 0,
  },
  categoryOption: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.paperBorder,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginRight: spacing.sm,
  },
  categoryOptionActive: {
    backgroundColor: colors.dashboard,
    borderColor: colors.dashboard,
  },
  categoryOptionText: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  categoryOptionTextActive: {
    color: colors.creamText,
  },
  editorSave: {
    minHeight: 38,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    backgroundColor: colors.dashboard,
  },
  editorSaveText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  emptyPanel: {
    marginTop: spacing.sm,
  },
  reviewBadge: {
    minWidth: 68,
    alignItems: 'center',
  },
  reviewBadgeValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  reviewBadgeLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 8,
  },
});
