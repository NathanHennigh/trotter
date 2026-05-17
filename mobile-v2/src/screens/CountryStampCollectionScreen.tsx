import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  BottomNav,
  IconButton,
  IconGlyph,
  PaperSurface,
  ScreenHeader,
  SegmentedFilterTabs,
  Stamp,
} from '../components/trotter/TrotterKit';
import { BottomNavTab, CountryStamp, countryStamps } from '../data/trotterMock';
import {
  getMe,
  getJobStatus,
  listUnparsedCandidates,
  requestDevToken,
  runQueryComparison,
  ScanJobStatus,
  signInWithGoogle,
  startGmailImport,
} from '../services/scanControls';
import { getApiBaseUrl, getStoredToken, hydrateStoredToken } from '../services/travelTrips';
import { colors, fonts, layout, spacing } from '../theme/trotterTheme';

export function CountryStampCollectionScreen({ active, onChange }: { active: BottomNavTab; onChange: (tab: BottomNavTab) => void }) {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [tab, setTab] = React.useState('all');
  const visited = countryStamps.filter((country) => country.visited).length;
  const visibleCountries = countryStamps.filter((country) => tab === 'all' || (tab === 'visited' ? country.visited : !country.visited));
  const screenPadding = width < 390 ? 16 : layout.screenPadding;
  const contentWidth = width - screenPadding * 2;
  const cardWidth = (contentWidth - layout.cardGap) / 2;

  return (
    <View style={[styles.screen, { paddingTop: insets.top + 12 }]}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: insets.bottom + layout.bottomNavHeight + 24 }}>
        <ScreenHeader
          title="COUNTRIES"
          subtitle="STAMP COLLECTION"
          leftAction={<IconButton variant="paper" shape="circle" icon={<IconGlyph name="globe" color={colors.ink} size={22} />} />}
          rightActions={[<CountryProgressBadge key="progress" visited={visited} total={195} />]}
        />
        <SegmentedFilterTabs
          activeKey={tab}
          onChange={setTab}
          tabs={[
            { key: 'all', label: 'ALL', count: countryStamps.length },
            { key: 'visited', label: 'VISITED', count: visited },
            { key: 'unvisited', label: 'UNVISITED', count: countryStamps.length - visited },
          ]}
        />
        <TemporaryScanPanel screenPadding={screenPadding} contentWidth={contentWidth} />
        <CountrySummaryMapCard visited={visited} screenPadding={screenPadding} contentWidth={contentWidth} />
        <View style={[styles.grid, { paddingHorizontal: screenPadding, gap: layout.cardGap }]}>
          {visibleCountries.map((country) => <CountryStampCard key={country.country} country={country} width={cardWidth} />)}
        </View>
        <PaperSurface radius={14} padding={spacing.lg} style={[styles.banner, { marginHorizontal: screenPadding, width: contentWidth }]}>
          <Text allowFontScaling={false} style={styles.bannerTitle}>COLLECT MORE STAMPS</Text>
          <Text maxFontSizeMultiplier={1.1} style={styles.bannerText}>New countries unlock when imported flights include an arrival airport outside your existing travel archive.</Text>
        </PaperSurface>
      </ScrollView>
      <BottomNav active={active} onChange={onChange} />
    </View>
  );
}

function TemporaryScanPanel({ screenPadding, contentWidth }: { screenPadding: number; contentWidth: number }) {
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState('Manual scanning only. Nothing here runs automatically.');
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [job, setJob] = React.useState<ScanJobStatus | null>(null);
  const [hasToken, setHasToken] = React.useState(() => Boolean(getStoredToken()));
  const [accountEmail, setAccountEmail] = React.useState<string | null>(null);

  React.useEffect(() => {
    hydrateStoredToken().then((token) => {
      if (!token) return;
      setHasToken(true);
      getMe(token).then((user) => setAccountEmail(user.email)).catch(() => setAccountEmail(null));
    });
  }, []);

  const runAction = async (label: string, action: () => Promise<string>) => {
    setBusy(label);
    try {
      setMessage(await action());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const startImport = () => runAction('import', async () => {
    const response = await startGmailImport();
    setJobId(response.job_id);
    setJob(null);
    return `Started Gmail import ${response.job_id.slice(0, 8)}. Use Poll Job to refresh counts.`;
  });

  const pollJob = () => runAction('poll', async () => {
    if (!jobId) return 'No current job id. Start Gmail Import first.';
    const status = await getJobStatus(jobId);
    setJob(status);
    return `Job ${status.state}: scanned ${status.scanned_count}, parsed ${status.parsed_count}, segments ${status.segment_count}.`;
  });

  return (
    <PaperSurface radius={14} padding={spacing.md} style={[styles.scanPanel, { marginHorizontal: screenPadding, width: contentWidth }]}>
      <View style={styles.scanHeader}>
        <View>
          <Text allowFontScaling={false} style={styles.scanTitle}>DEV SCANS</Text>
          <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.scanSub}>{getApiBaseUrl()}</Text>
        </View>
        <View style={[styles.tokenPill, hasToken && styles.tokenPillReady]}>
          <Text allowFontScaling={false} style={[styles.tokenText, hasToken && styles.tokenTextReady]}>{hasToken ? 'TOKEN' : 'NO TOKEN'}</Text>
        </View>
      </View>

      <View style={styles.scanButtonGrid}>
        <ScanButton
          label="Google"
          disabled={busy !== null}
          busy={busy === 'google'}
          onPress={() => runAction('google', async () => {
            const user = await signInWithGoogle();
            setHasToken(true);
            setAccountEmail(user.email);
            return `Connected Google for ${user.email}.`;
          })}
        />
        <ScanButton
          label="Dev Token"
          disabled={busy !== null}
          busy={busy === 'token'}
          onPress={() => runAction('token', async () => {
            const token = await requestDevToken();
            setHasToken(true);
            setAccountEmail(token.email);
            return `Stored token for ${token.email}.`;
          })}
        />
        <ScanButton label="Gmail Import" disabled={busy !== null} busy={busy === 'import'} onPress={startImport} />
        <ScanButton label="Poll Job" disabled={busy !== null || !jobId} busy={busy === 'poll'} onPress={pollJob} />
        <ScanButton
          label="Query Test"
          disabled={busy !== null}
          busy={busy === 'queries'}
          onPress={() => runAction('queries', async () => {
            const result = await runQueryComparison();
            return `v1 ${result.v1_count}, v2 ${result.v2_count}, v3 ${result.v3_count}. Parser comparison continues on backend.`;
          })}
        />
        <ScanButton
          label="Unparsed"
          disabled={busy !== null}
          busy={busy === 'unparsed'}
          onPress={() => runAction('unparsed', async () => {
            const result = await listUnparsedCandidates(25);
            return `${result.total} review-required messages. Latest: ${result.candidates[0]?.subject ?? 'none'}`;
          })}
        />
      </View>

      {job ? (
        <View style={styles.jobStrip}>
          <DevMetric label="STATE" value={job.state} />
          <DevMetric label="SCAN" value={String(job.scanned_count)} />
          <DevMetric label="PARSE" value={String(job.parsed_count)} />
          <DevMetric label="SEG" value={String(job.segment_count)} />
        </View>
      ) : null}
      <Text maxFontSizeMultiplier={1.05} style={styles.scanMessage}>{accountEmail ? `Signed in as ${accountEmail}. ${message}` : message}</Text>
    </PaperSurface>
  );
}

function ScanButton({
  label,
  onPress,
  disabled,
  busy,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <Pressable onPress={onPress} disabled={disabled} style={[styles.scanButton, disabled && styles.scanButtonDisabled]}>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.scanButtonText}>{busy ? '...' : label}</Text>
    </Pressable>
  );
}

function DevMetric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.devMetric}>
      <Text allowFontScaling={false} style={styles.devMetricLabel}>{label}</Text>
      <Text allowFontScaling={false} numberOfLines={1} adjustsFontSizeToFit style={styles.devMetricValue}>{value}</Text>
    </View>
  );
}

function CountryProgressBadge({ visited, total }: { visited: number; total: number }) {
  return (
    <PaperSurface radius={999} padding={8} style={styles.badge}>
      <Text allowFontScaling={false} style={styles.badgeValue}>{visited} / {total}</Text>
      <Text allowFontScaling={false} style={styles.badgeLabel}>VISITED</Text>
    </PaperSurface>
  );
}

function CountrySummaryMapCard({ visited, screenPadding, contentWidth }: { visited: number; screenPadding: number; contentWidth: number }) {
  return (
    <PaperSurface radius={16} padding={spacing.lg} style={[styles.mapCard, { marginHorizontal: screenPadding, width: contentWidth }]}>
      <View style={styles.mapTop}>
        <View>
          <Text allowFontScaling={false} style={styles.mapTitle}>WORLD SUMMARY</Text>
          <Text maxFontSizeMultiplier={1.05} style={styles.mapSub}>{visited} countries stamped</Text>
        </View>
        <IconGlyph name="globe" color={colors.tealDeep} size={34} />
      </View>
      <View style={styles.miniMap}>
        <View style={[styles.landMass, styles.landA]} />
        <View style={[styles.landMass, styles.landB]} />
        <View style={[styles.landMass, styles.landC]} />
        <View style={[styles.routeArc, styles.routeArcA]} />
        <View style={[styles.routeArc, styles.routeArcB]} />
      </View>
      <View style={styles.legend}>
        <LegendDot color={colors.green} label="visited" />
        <LegendDot color={colors.paperBorder} label="not visited" />
        <LegendDot color={colors.mustard} label="in transit" />
      </View>
    </PaperSurface>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendItem}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.legendText}>{label}</Text>
    </View>
  );
}

function CountryStampCard({ country, width }: { country: CountryStamp; width: number }) {
  return (
    <PaperSurface radius={12} padding={spacing.sm} style={[styles.countryCard, { width }, !country.visited && styles.countryCardMuted]}>
      <Stamp
        type={country.stampType}
        color={country.color}
        title={country.country.toUpperCase()}
        subtitle={`${country.city}${country.airportCode ? ` (${country.airportCode})` : ''}`}
        date={country.firstVisitDate}
        footer={country.visited ? undefined : 'UNSTAMPED'}
        landmark={country.landmark}
        faded={!country.visited}
        size={width < 160 ? 'sm' : 'md'}
      />
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.countryName}>{country.country}</Text>
      <Text maxFontSizeMultiplier={1.05} numberOfLines={1} style={styles.countryMeta}>{country.visited ? country.firstVisitDate : `${country.city} awaits`}</Text>
    </PaperSurface>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.paperSoft,
  },
  badge: {
    minWidth: 68,
    alignItems: 'center',
  },
  badgeValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 12,
  },
  badgeLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 8,
  },
  mapCard: {
    marginTop: spacing.md,
  },
  scanPanel: {
    marginTop: spacing.md,
  },
  scanHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  scanTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    letterSpacing: 1,
  },
  scanSub: {
    color: colors.mutedInk,
    fontFamily: fonts.mono,
    fontSize: 10,
    marginTop: 4,
  },
  tokenPill: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.red,
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  tokenPillReady: {
    borderColor: colors.green,
  },
  tokenText: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 9,
  },
  tokenTextReady: {
    color: colors.green,
  },
  scanButtonGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  scanButton: {
    minHeight: 38,
    minWidth: 96,
    flexGrow: 1,
    flexBasis: '30%',
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.dashboard,
    borderWidth: 1,
    borderColor: colors.darkBorder,
    paddingHorizontal: spacing.sm,
  },
  scanButtonDisabled: {
    opacity: 0.48,
  },
  scanButtonText: {
    color: colors.creamText,
    fontFamily: fonts.sansBold,
    fontSize: 11,
  },
  jobStrip: {
    marginTop: spacing.md,
    flexDirection: 'row',
    borderRadius: 8,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  devMetric: {
    flex: 1,
    minWidth: 0,
    padding: spacing.sm,
    backgroundColor: colors.paperSoft,
    borderRightWidth: 1,
    borderRightColor: colors.paperBorder,
  },
  devMetricLabel: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 8,
  },
  devMetricValue: {
    color: colors.ink,
    fontFamily: fonts.mono,
    fontSize: 12,
    marginTop: 3,
  },
  scanMessage: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    lineHeight: 17,
    marginTop: spacing.md,
  },
  mapTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  mapTitle: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 14,
  },
  mapSub: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 12,
    marginTop: 2,
  },
  miniMap: {
    height: 132,
    marginTop: spacing.md,
    borderRadius: 10,
    overflow: 'hidden',
    backgroundColor: '#D8C7A6',
    borderWidth: 1,
    borderColor: colors.paperBorder,
  },
  landMass: {
    position: 'absolute',
    backgroundColor: colors.green,
    opacity: 0.72,
  },
  landA: {
    left: 24,
    top: 36,
    width: 94,
    height: 46,
    borderRadius: 28,
  },
  landB: {
    left: 132,
    top: 42,
    width: 72,
    height: 38,
    borderRadius: 20,
  },
  landC: {
    right: 34,
    top: 28,
    width: 98,
    height: 54,
    borderRadius: 30,
  },
  routeArc: {
    position: 'absolute',
    borderTopWidth: 2,
    borderColor: colors.red,
    opacity: 0.75,
  },
  routeArcA: {
    left: 82,
    top: 32,
    width: 164,
    height: 80,
    borderRadius: 100,
    transform: [{ rotate: '-8deg' }],
  },
  routeArcB: {
    left: 44,
    top: 54,
    width: 244,
    height: 94,
    borderRadius: 140,
    transform: [{ rotate: '8deg' }],
  },
  legend: {
    flexDirection: 'row',
    gap: spacing.md,
    marginTop: spacing.md,
    flexWrap: 'wrap',
  },
  legendItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansBold,
    fontSize: 10,
  },
  grid: {
    marginTop: spacing.lg,
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  countryCard: {
    height: 178,
    alignItems: 'center',
    justifyContent: 'flex-start',
    overflow: 'hidden',
  },
  countryCardMuted: {
    backgroundColor: '#E9DCC4',
  },
  countryName: {
    color: colors.ink,
    fontFamily: fonts.sansBold,
    fontSize: 13,
    marginTop: spacing.sm,
  },
  countryMeta: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 11,
    marginTop: 2,
  },
  banner: {
    marginTop: spacing.lg,
  },
  bannerTitle: {
    color: colors.red,
    fontFamily: fonts.sansBold,
    fontSize: 13,
  },
  bannerText: {
    color: colors.mutedInk,
    fontFamily: fonts.sansRegular,
    fontSize: 13,
    marginTop: 5,
    lineHeight: 18,
  },
});
