import React from 'react';
import {
  ActivityIndicator, BackHandler, KeyboardAvoidingView, Platform, RefreshControl,
  ScrollView, Share, StyleSheet, Text, TextInput, View,
} from 'react-native';
import * as Crypto from 'expo-crypto';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { WWHeader, WWIcon } from '../components/world-window/WorldWindowUI';
import { PressFeedback } from '../components/world-window/motion';
import {
  acceptanceMessage, arrivalDayOffset, flightDate, flightRoute, flightTime, groupRetainedBookings,
  passengerName, shareStatus, validateFlightShare, type RetainedBooking,
} from '../components/world-window/sharing/flightSharingPresentation';
import {
  flightSharing, type AcceptedFlightShare, type FlightShare, type FlightSharingInbox,
  type RetainedFlight, type SharedFlight,
} from '../services/flightSharing';
import { useTravelTrips } from '../services/travelTrips';
import { colors, fonts } from '../theme/trotterTheme';
import { selectionHaptic } from '../utils/experiencePreferences';

type InboxTab = 'send' | 'received' | 'sent';
type Page = { kind: 'inbox' } | { kind: 'compose'; group: RetainedBooking } | { kind: 'detail'; share: FlightShare; outgoing: boolean };
const EMPTY: FlightSharingInbox = { items: [], incoming: [], outgoing: [] };
const STATUS: Record<FlightShare['status'], string> = {
  pending: 'Awaiting acceptance', accepted: 'Accepted', declined: 'Declined', revoked: 'Revoked', expired: 'Expired',
};
const canChoose = (item: RetainedFlight) => Boolean(item.flight && item.status !== 'canceled' && item.status !== 'belongs_to_you'
  && (item.shareable || item.requires_assignment));

export function FlightSharingScreen({ onBack, invitationToken, onInvitationConsumed, onAccepted }: {
  onBack: () => void;
  invitationToken?: string;
  onInvitationConsumed?: () => void;
  onAccepted?: () => void;
}) {
  const insets = useSafeAreaInsets();
  const { accountId, accountEmail, refresh: refreshTravel } = useTravelTrips();
  const [data, setData] = React.useState<FlightSharingInbox>(EMPTY);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [tab, setTab] = React.useState<InboxTab>('send');
  const [page, setPage] = React.useState<Page>({ kind: 'inbox' });
  const pageRef = React.useRef(page);
  pageRef.current = page;
  const [selected, setSelected] = React.useState<string[]>([]);
  const [name, setName] = React.useState('');
  const [email, setEmail] = React.useState('');
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [busy, setBusy] = React.useState('');
  const [resolving, setResolving] = React.useState(false);
  const [resolveFailed, setResolveFailed] = React.useState(false);
  const [retryInvitation, setRetryInvitation] = React.useState(0);
  const [copyLink, setCopyLink] = React.useState<{ id: string; url: string }>();
  const alive = React.useRef(true);
  const busyRef = React.useRef(false);
  const requestVersion = React.useRef(0);
  const createRequest = React.useRef<{ fingerprint: string; id: string } | undefined>(undefined);
  const consumed = React.useRef(onInvitationConsumed);
  consumed.current = onInvitationConsumed;
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const groups = React.useMemo(() => groupRetainedBookings(data.items), [data.items]);
  const pendingCount = data.incoming.filter(share => shareStatus(share) === 'pending').length;

  const load = React.useCallback(async (initial = false) => {
    const version = ++requestVersion.current;
    if (!initial) setRefreshing(true);
    try {
      const result = await flightSharing.inbox();
      if (alive.current && version === requestVersion.current) setData(result);
    } catch (cause) {
      if (alive.current && version === requestVersion.current) setError(message(cause));
    } finally {
      if (alive.current && version === requestVersion.current) { setLoading(false); setRefreshing(false); }
    }
  }, []);
  React.useEffect(() => {
    setData(EMPTY); setLoading(true); setPage({ kind: 'inbox' });
    setSelected([]); setName(''); setEmail(''); setNotice(''); setError(''); setCopyLink(undefined);
    createRequest.current = undefined;
    void load(true);
  }, [load, accountId]);
  React.useEffect(() => {
    if (!invitationToken) { setResolving(false); return; }
    let current = true;
    setResolving(true); setResolveFailed(false); setError(''); setNotice('');
    void flightSharing.resolve(invitationToken).then(share => {
      if (!current || !alive.current) return;
      const outgoing = share.recipient_email.toLowerCase() !== accountEmail?.toLowerCase();
      setNotice(''); setError('');
      setTab(outgoing ? 'sent' : 'received');
      setPage({ kind: 'detail', share, outgoing });
      setResolving(false);
      consumed.current?.();
    }).catch(cause => {
      if (current && alive.current) { setError(message(cause)); setResolveFailed(true); }
    }).finally(() => { if (current && alive.current) setResolving(false); });
    return () => { current = false; };
  }, [invitationToken, accountEmail, retryInvitation]);

  const back = React.useCallback(() => {
    if (busyRef.current) return;
    if (resolving || resolveFailed) consumed.current?.();
    setResolveFailed(false); setError(''); setNotice('');
    if (page.kind !== 'inbox') setPage({ kind: 'inbox' });
    else onBack();
  }, [page.kind, onBack, resolving, resolveFailed]);
  React.useEffect(() => {
    if (Platform.OS === 'web') return;
    const sub = BackHandler.addEventListener('hardwareBackPress', () => { back(); return true; });
    return () => sub.remove();
  }, [back]);

  const run = async (label: string, work: () => Promise<void>) => {
    if (busyRef.current) return;
    const initialPage = pageKey(pageRef.current);
    busyRef.current = true; setBusy(label); setError(''); setNotice('');
    try { await work(); }
    catch (cause) { if (alive.current && initialPage === pageKey(pageRef.current)) setError(message(cause)); }
    finally { busyRef.current = false; if (alive.current) setBusy(''); }
  };
  const openBooking = (group: RetainedBooking) => {
    setSelected(group.items.filter(canChoose).map(item => item.id));
    setName(group.passenger); setEmail(''); setError(''); setNotice('');
    createRequest.current = undefined;
    setPage({ kind: 'compose', group });
  };
  const openShare = (share: FlightShare, outgoing: boolean) => {
    setError(''); setNotice(''); setPage({ kind: 'detail', share, outgoing });
  };
  const choose = (id: string) => {
    if (busyRef.current) return;
    selectionHaptic(); setError('');
    setSelected(current => current.includes(id) ? current.filter(key => key !== id) : [...current, id]);
  };
  const assignSelection = async () => {
    if (page.kind !== 'compose') return;
    if (name.trim().length < 2 || !selected.length) throw new Error('Choose flights and enter the traveler’s name.');
    const updated: RetainedFlight[] = [];
    for (const item of page.group.items.filter(row => selected.includes(row.id))) {
      if (!alive.current) return;
      if (passengerName(item) !== name.trim()) updated.push(await flightSharing.assign(item.id, name.trim()));
    }
    if (!alive.current) return;
    const byId = new Map(updated.map(item => [item.id, item]));
    setData(current => ({ ...current, items: current.items.map(item => byId.get(item.id) || item) }));
    setPage(current => current.kind === 'compose' ? { ...current, group: { ...current.group,
      passenger: name.trim(), items: current.group.items.map(item => byId.get(item.id) || item) } } : current);
  };
  const saveName = () => void run('Saving traveler…', async () => {
    await assignSelection();
    if (alive.current) setNotice('Traveler saved. These flights remain separate from your own trips.');
  });
  const create = () => void run('Creating share…', async () => {
    const originalPage = pageKey(pageRef.current);
    const validation = validateFlightShare(name, email, selected.length, accountEmail);
    if (validation) throw new Error(validation);
    await assignSelection();
    if (!alive.current) return;
    const values = { item_ids: [...selected].sort(), passenger_name: name.trim(), recipient_email: email.trim().toLowerCase() };
    const fingerprint = JSON.stringify(values);
    if (createRequest.current?.fingerprint !== fingerprint) createRequest.current = { fingerprint, id: Crypto.randomUUID() };
    const result = await flightSharing.create({ ...values, client_request_id: createRequest.current.id });
    if (!alive.current) return;
    setData(current => ({ ...current, outgoing: [result.share, ...current.outgoing.filter(share => share.id !== result.share.id)] }));
    if (pageKey(pageRef.current) === originalPage) {
      setTab('sent'); setPage({ kind: 'detail', share: result.share, outgoing: true });
      setNotice('Ready for the recipient. Share the link to let them know.');
    }
    selectionHaptic('confirmation');
    void load();
  });
  const act = (action: 'accept' | 'decline' | 'revoke', share: FlightShare) => void run(
    action === 'accept' ? 'Adding flights…' : action === 'decline' ? 'Declining…' : 'Revoking…', async () => {
      const result = action === 'accept' ? await flightSharing.accept(share.id)
        : action === 'decline' ? await flightSharing.decline(share.id) : await flightSharing.revoke(share.id);
      if (!alive.current) return;
      setPage(current => current.kind === 'detail' && current.share.id === share.id ? { ...current, share: result.share } : current);
      setData(current => ({ ...current,
        incoming: current.incoming.map(row => row.id === share.id ? result.share : row),
        outgoing: current.outgoing.map(row => row.id === share.id ? result.share : row),
      }));
      if ('added_flights' in result) {
        const accepted = result as AcceptedFlightShare;
        if (pageRef.current.kind === 'detail' && pageRef.current.share.id === share.id) setNotice(acceptanceMessage(accepted.added_flights, accepted.existing_flights));
        selectionHaptic('confirmation');
        // Acceptance is already durable; a refresh failure must not imply it failed.
        void refreshTravel().catch(() => {
          if (alive.current && pageRef.current.kind === 'detail' && pageRef.current.share.id === share.id) setNotice(`${acceptanceMessage(accepted.added_flights, accepted.existing_flights)} Refresh Trips to see the update.`);
        });
        onAccepted?.();
      } else if (pageRef.current.kind === 'detail' && pageRef.current.share.id === share.id) setNotice(action === 'revoke' ? 'The invitation can no longer be accepted.' : 'These flights were not added to your history.');
    },
  );
  const shareLink = (share: FlightShare) => void run('Preparing link…', async () => {
    const result = await flightSharing.link(share.id);
    if (!alive.current || pageRef.current.kind !== 'detail' || pageRef.current.share.id !== share.id) return;
    const browser = (globalThis as { navigator?: { share?: unknown; clipboard?: { writeText: (value: string) => Promise<void> } } }).navigator;
    if (Platform.OS === 'web' && !browser?.share) {
      try {
        if (!browser?.clipboard) throw new Error('Clipboard unavailable');
        await browser.clipboard.writeText(result.share_url);
        if (alive.current && pageRef.current.kind === 'detail' && pageRef.current.share.id === share.id) setNotice('Invitation link copied.');
      } catch {
        if (alive.current && pageRef.current.kind === 'detail' && pageRef.current.share.id === share.id) {
          setCopyLink({ id: share.id, url: result.share_url }); setNotice('Select and copy the invitation link below.');
        }
      }
      return;
    }
    try { await Share.share({ title: 'Your flights in Trotter', message: `I saved flights for you in Trotter. Review and add them here: ${result.share_url}` }); }
    catch (cause) { if (!(cause instanceof Error && cause.name === 'AbortError')) throw cause; }
  });

  const header = page.kind === 'compose' ? 'Prepare flights' : page.kind === 'detail' ? 'Shared flights' : 'Flights for others';
  const share = page.kind === 'detail' ? page.share : undefined;
  const status = share ? shareStatus(share) : undefined;
  const groupItems = page.kind === 'compose' ? page.group.items : [];
  const selectedItems = groupItems.filter(item => selected.includes(item.id));
  const changedName = selectedItems.some(item => passengerName(item) !== name.trim());
  return <KeyboardAvoidingView style={[s.screen, { paddingTop: insets.top }]} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <WWHeader title={header} onBack={back} />
    {page.kind === 'inbox' && !resolving && <View style={s.tabs} accessibilityRole="tablist">
      {([['send', 'To send'], ['received', 'Received'], ['sent', 'Sent']] as const).map(([key, title]) => <PressFeedback key={key}
        accessibilityRole="tab" accessibilityState={{ selected: tab === key }} onPress={() => { setTab(key); setError(''); setNotice(''); }} style={[s.tab, tab === key && s.tabSelected]}>
        <Text style={[s.tabText, tab === key && s.tabTextSelected]}>{title}</Text>
        {key === 'received' && pendingCount > 0 ? <View style={s.count}><Text style={s.countText}>{pendingCount}</Text></View> : null}
      </PressFeedback>)}
    </View>}
    <ScrollView keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false}
      contentContainerStyle={[s.content, { paddingBottom: insets.bottom + 32 }]}
      refreshControl={page.kind === 'inbox' ? <RefreshControl refreshing={refreshing} onRefresh={() => { setError(''); void load(); }} tintColor={colors.blue} /> : undefined}>
      {error ? <View style={s.feedback}><Text style={s.error} accessibilityRole="alert">{error}</Text>
        {resolveFailed ? <Action label="Try invitation again" secondary onPress={() => setRetryInvitation(value => value + 1)} disabled={!!busy || resolving} />
          : page.kind === 'inbox' ? <Action label="Retry" secondary onPress={() => { setError(''); void load(); }} disabled={refreshing} /> : null}
      </View> : null}
      {notice ? <View style={s.notice}><Text style={s.noticeText} accessibilityLiveRegion="polite">{notice}</Text></View> : null}
      {(resolving || (loading && page.kind === 'inbox')) ? <View style={s.loading}><ActivityIndicator color={colors.blue} /><Text style={s.secondary}>{resolving ? 'Opening your invitation…' : 'Loading flights…'}</Text></View> : null}

      {!loading && !resolving && page.kind === 'inbox' && tab === 'send' && <>
        <Text style={s.intro}>Tickets found in your email for other travelers. Choose a booking to prepare a share.</Text>
        {groups.length ? groups.map(group => <PressFeedback key={group.key} accessibilityRole="button" accessibilityLabel={`Prepare flights for ${group.passenger || 'an unnamed traveler'}`} onPress={() => openBooking(group)} style={s.booking}>
          <View style={s.cardTop}><Text style={s.overline}>{group.passenger ? 'TRAVELER' : 'TRAVELER NOT NAMED'}</Text><WWIcon name="trips" color={colors.blue} size={20} /></View>
          <Text style={s.cardTitle}>{group.passenger || 'Assign a traveler'}</Text>
          <Text style={s.route} numberOfLines={2}>{flightRoute(group.items.flatMap(item => item.flight ? [item.flight] : [])) || 'Flight details incomplete'}</Text>
          <View style={s.cardBottom}><View style={s.flex}><Text style={s.secondary}>{flightDate(group.items[0]?.flight?.travel_date)}</Text><Text style={s.small}>{group.items.length} {group.items.length === 1 ? 'flight' : 'flights'}{group.reference ? ` · Booking ${group.reference}` : ''}</Text></View><WWIcon name="arrow" color={colors.blue} size={20} /></View>
        </PressFeedback>) : !error ? <Empty title="No tickets waiting" copy="When a flight in your email belongs to someone else, it will appear here without changing your own travel history." /> : null}
      </>}
      {!loading && !resolving && page.kind === 'inbox' && tab !== 'send' && <>
        {(tab === 'received' ? data.incoming : data.outgoing).length ? (tab === 'received' ? data.incoming : data.outgoing).map(item => <PressFeedback key={item.id} accessibilityRole="button" accessibilityLabel={`View ${item.flights.length} shared flights for ${item.passenger_name}`} onPress={() => openShare(item, tab === 'sent')} style={s.booking}>
          <View style={s.cardTop}><Text style={[s.overline, shareStatus(item) === 'accepted' && s.accepted]}>{STATUS[shareStatus(item)].toUpperCase()}</Text><WWIcon name="mail" color={colors.blue} size={19} /></View>
          <Text style={s.cardTitle}>{item.passenger_name}</Text>
          <Text style={s.route} numberOfLines={2}>{flightRoute(item.flights)}</Text>
          <View style={s.cardBottom}><View style={s.flex}><Text style={s.secondary}>{tab === 'received' ? `From ${item.sender_name || 'a Trotter traveler'}` : `To ${item.recipient_email}`}</Text><Text style={s.small}>{item.flights.length} {item.flights.length === 1 ? 'flight' : 'flights'} · {flightDate(item.flights[0]?.travel_date)}</Text></View><WWIcon name="chevron" color={colors.blue} size={17} /></View>
        </PressFeedback>) : !error ? <Empty title={tab === 'received' ? 'Nothing received yet' : 'No shares yet'} copy={tab === 'received' ? 'Flights shared with your Google account email will appear here. You choose whether to add them.' : 'Prepare a booking in To send. Your invitations and their status will stay here.'} /> : null}
      </>}
      {!resolving && page.kind === 'compose' && <>
        <View style={s.summary}><Text style={s.overline}>SELECT FLIGHTS</Text><Text style={s.intro}>Only the selected flights will be shared.</Text></View>
        <View style={s.flightStack}>{groupItems.map(item => <FlightRow key={item.id} flight={item.flight} selected={selected.includes(item.id)}
          disabled={!canChoose(item) || !!busy} onPress={() => choose(item.id)} note={!canChoose(item) ? item.share_blocked_reason || 'This flight cannot be shared yet.' : undefined} />)}</View>
        <View style={s.formSection}>
          <Text style={s.label}>Traveler’s name</Text>
          <TextInput accessibilityLabel="Traveler’s name" value={name} onChangeText={setName} editable={!busy && !groupItems.some(item => item.passenger_name)} autoCapitalize="words" autoCorrect={false} maxLength={100} placeholder="Name on the ticket" placeholderTextColor={colors.mutedInk} style={s.input} />
          {groupItems.some(item => item.passenger_name) ? <Text style={s.small}>Name recorded on the ticket.</Text> : null}
          {selectedItems.some(item => !passengerName(item)) ? <Text style={s.small}>The email did not identify the traveler. Enter their name before sharing.</Text> : null}
          {changedName ? <PressFeedback accessibilityRole="button" disabled={!!busy || !name.trim() || !selected.length} onPress={saveName} style={s.inlineAction}><Text style={s.linkText}>Save traveler</Text></PressFeedback> : null}
          <Text style={[s.label, s.emailLabel]}>Recipient’s email</Text>
          <TextInput accessibilityLabel="Recipient’s email" value={email} onChangeText={setEmail} editable={!busy} keyboardType="email-address" autoCapitalize="none" autoCorrect={false} textContentType="emailAddress" maxLength={254} placeholder="Their Google account email" placeholderTextColor={colors.mutedInk} style={s.input} />
          <Text style={s.small}>They’ll sign in with this address to review the flights. They can join Trotter if they don’t have it yet.</Text>
        </View>
        <View style={s.privacy}><WWIcon name="passport" color={colors.mutedInk} size={19} /><Text style={[s.small, s.flex]}>Shares include flight details only. Booking codes, payment details, and original emails stay private.</Text></View>
        <Action label={busy || `Create share · ${selected.length} ${selected.length === 1 ? 'flight' : 'flights'}`} onPress={create} disabled={!!busy || !selected.length} loading={!!busy} />
      </>}
      {!resolving && page.kind === 'detail' && share && <>
        <View style={s.shareIdentity}>
          <Text style={[s.overline, status === 'accepted' && s.accepted]}>{STATUS[status!].toUpperCase()}</Text>
          <Text style={s.recipientName}>{share.passenger_name}</Text>
          <Text style={s.secondary}>{page.outgoing ? `To ${share.recipient_email}` : `From ${share.sender_name || 'a Trotter traveler'}`}</Text>
          {status === 'pending' ? <Text style={s.small}>Accept by {flightDate(share.expires_at)}</Text> : null}
        </View>
        <View style={s.flightStack}>{share.flights.map((flight, index) => <FlightRow key={`${flight.travel_date}:${flight.dep_airport}:${flight.flight_number}:${index}`} flight={flight} />)}</View>
        {status === 'pending' && page.outgoing && <>
          <Text style={s.intro}>These flights are waiting for {share.recipient_email} to accept. You can send the link through your usual messaging app.</Text>
          <Action label={busy || 'Share invitation link'} onPress={() => shareLink(share)} disabled={!!busy} loading={!!busy} />
          {copyLink?.id === share.id ? <Text selectable style={s.copyLink} accessibilityLabel="Invitation link">{copyLink.url}</Text> : null}
          <Action label="Revoke invitation" secondary onPress={() => act('revoke', share)} disabled={!!busy} />
        </>}
        {status === 'pending' && !page.outgoing && <>
          <Text style={s.intro}>Accept if these flights belong to you. They’ll be added to your trips, globe, and passport. Flights already in your history won’t be added twice.</Text>
          <Action label={busy || 'Accept flights'} onPress={() => act('accept', share)} disabled={!!busy} loading={!!busy} />
          <Action label="These aren’t mine" secondary onPress={() => act('decline', share)} disabled={!!busy} />
        </>}
        {status && status !== 'pending' ? <Text style={s.intro}>{status === 'accepted'
          ? page.outgoing ? 'The recipient accepted these flights into their travel history.' : 'These flights are in your travel history.'
          : status === 'expired' ? 'This invitation has expired. Ask the sender to create another share.'
          : status === 'revoked' ? 'The sender revoked this invitation. It can no longer be accepted.'
          : 'This invitation was declined. No flights were added.'}</Text> : null}
        {!page.outgoing && status === 'pending' ? <Text style={s.footnote}>This adds a travel record, not ownership of an airline ticket.</Text> : null}
      </>}
    </ScrollView>
  </KeyboardAvoidingView>;
}

function FlightRow({ flight, onPress, selected, disabled, note }: {
  flight: SharedFlight | null; onPress?: () => void; selected?: boolean; disabled?: boolean; note?: string;
}) {
  const content = <>
    <View style={s.flightTop}><Text style={s.flightDate}>{flightDate(flight?.travel_date)}</Text><Text style={s.flightNumber}>{flight?.flight_number || flight?.airline || ''}</Text></View>
    <View style={s.flightRoute}>
      {onPress ? <View style={[s.checkbox, selected && s.checkboxSelected]}>{selected ? <WWIcon name="check" color={colors.paperSoft} size={14} /> : null}</View> : null}
      <View style={s.airport}><Text maxFontSizeMultiplier={1.35} style={s.airportCode}>{flight?.dep_airport || '—'}</Text>{flightTime(flight?.dep_time) ? <Text style={s.small}>{flightTime(flight?.dep_time)}</Text> : null}</View>
      <View style={s.routeRule}><View style={s.rule} /><WWIcon name="arrow" size={19} color={colors.copper} /><View style={s.rule} /></View>
      <View style={[s.airport, s.arrival]}><Text maxFontSizeMultiplier={1.35} style={s.airportCode}>{flight?.arr_airport || '—'}</Text>{flightTime(flight?.arr_time) ? <Text style={s.small}>{flightTime(flight?.arr_time)}</Text> : null}{arrivalDayOffset(flight) > 0 ? <Text style={s.dayOffset}>+{arrivalDayOffset(flight)} {arrivalDayOffset(flight) === 1 ? 'day' : 'days'}</Text> : null}</View>
    </View>
    {flight?.airline && flight.flight_number ? <Text style={s.small}>{flight.airline}</Text> : null}
    {note ? <Text style={s.blockedNote}>{note}</Text> : null}
  </>;
  return onPress ? <PressFeedback accessibilityRole="checkbox" accessibilityLabel={`${flight?.dep_airport || 'Unknown airport'} to ${flight?.arr_airport || 'unknown airport'}, ${flightDate(flight?.travel_date)}`}
    accessibilityState={{ checked: selected, disabled }} disabled={disabled} onPress={onPress} style={[s.flight, selected && s.flightSelected, disabled && s.disabledFlight]}>{content}</PressFeedback>
    : <View style={s.flight}>{content}</View>;
}
function Action({ label, onPress, secondary = false, disabled = false, loading = false }: {
  label: string; onPress: () => void; secondary?: boolean; disabled?: boolean; loading?: boolean;
}) {
  return <PressFeedback accessibilityRole="button" accessibilityState={{ disabled, busy: loading }} disabled={disabled} onPress={onPress} style={[s.action, secondary && s.secondaryAction, disabled && s.disabled]}>
    {loading ? <ActivityIndicator size="small" color={secondary ? colors.blue : colors.paperSoft} /> : null}
    <Text style={[s.actionText, secondary && s.secondaryActionText]}>{label}</Text>
  </PressFeedback>;
}
function Empty({ title, copy }: { title: string; copy: string }) {
  return <View style={s.empty}><View style={s.emptyIcon}><WWIcon name="mail" size={30} color={colors.blue} /></View><Text style={s.emptyTitle}>{title}</Text><Text style={s.emptyCopy}>{copy}</Text></View>;
}
function message(cause: unknown): string { return cause instanceof Error ? cause.message : 'Something went wrong. Please try again.'; }
function pageKey(page: Page): string { return page.kind === 'compose' ? `compose:${page.group.key}` : page.kind === 'detail' ? `detail:${page.share.id}` : 'inbox'; }

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft }, content: { width: '100%', maxWidth: 640, alignSelf: 'center', paddingHorizontal: 24 },
  tabs: { flexDirection: 'row', paddingHorizontal: 24, marginBottom: 16, borderBottomWidth: 1, borderBottomColor: colors.paperBorder, maxWidth: 640, alignSelf: 'center', width: '100%' },
  tab: { flex: 1, minHeight: 46, paddingHorizontal: 15, flexDirection: 'row', gap: 6, justifyContent: 'center', alignItems: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' }, tabSelected: { borderBottomColor: colors.blue },
  tabText: { fontFamily: fonts.sans, fontSize: 13, color: colors.mutedInk }, tabTextSelected: { color: colors.blue }, count: { minWidth: 18, height: 18, borderRadius: 9, backgroundColor: colors.blue, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 4 }, countText: { fontFamily: fonts.mono, fontSize: 9, color: colors.paperSoft },
  intro: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk, marginBottom: 18, marginTop: 4 },
  booking: { backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 5, padding: 17, marginBottom: 14 },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 }, overline: { fontFamily: fonts.mono, fontSize: 9, lineHeight: 15, letterSpacing: .8, color: colors.mutedInk },
  cardTitle: { fontFamily: fonts.display, fontSize: 26, lineHeight: 32, color: colors.ink, marginTop: 9 }, route: { fontFamily: fonts.mono, fontSize: 13, lineHeight: 22, color: colors.blue, marginTop: 12 },
  cardBottom: { borderTopWidth: 1, borderStyle: 'dashed', borderTopColor: colors.paperBorder, marginTop: 15, paddingTop: 12, flexDirection: 'row', alignItems: 'center', gap: 12 },
  secondary: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.mutedInk }, small: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk }, flex: { flex: 1 },
  loading: { paddingVertical: 56, alignItems: 'center', gap: 12 }, feedback: { backgroundColor: colors.paperInset, padding: 14, marginBottom: 16, borderLeftWidth: 2, borderColor: colors.redDeep }, error: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.redDeep },
  notice: { padding: 14, marginBottom: 18, borderLeftWidth: 2, borderColor: colors.green, backgroundColor: colors.paperDeep }, noticeText: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.ink },
  summary: { paddingTop: 4 }, flightStack: { gap: 10, marginBottom: 18 }, flight: { backgroundColor: colors.paper, borderColor: colors.paperBorder, borderWidth: 1, borderRadius: 4, padding: 15, gap: 7 }, flightSelected: { borderColor: colors.blue }, disabledFlight: { backgroundColor: colors.paperInset },
  flightTop: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', gap: 5 }, flightDate: { fontFamily: fonts.mono, fontSize: 10, lineHeight: 16, color: colors.mutedInk }, flightNumber: { fontFamily: fonts.mono, fontSize: 10, lineHeight: 16, color: colors.blue },
  flightRoute: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 5 }, airport: { gap: 1 }, airportCode: { fontFamily: fonts.display, fontSize: 33, lineHeight: 39, color: colors.ink }, arrival: { alignItems: 'flex-end' }, routeRule: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 4 }, rule: { flex: 1, height: 1, backgroundColor: colors.paperBorder },
  checkbox: { width: 21, height: 21, borderWidth: 1, borderRadius: 3, borderColor: colors.paperBorder, alignItems: 'center', justifyContent: 'center' }, checkboxSelected: { borderColor: colors.blue, backgroundColor: colors.blue }, blockedNote: { color: colors.redDeep, fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17 },
  dayOffset: { fontFamily: fonts.mono, fontSize: 9, lineHeight: 15, color: colors.copper },
  formSection: { borderTopWidth: 1, borderColor: colors.paperBorder, paddingTop: 20, marginBottom: 18 }, label: { fontFamily: fonts.sans, fontSize: 13, color: colors.ink, marginBottom: 9 }, input: { backgroundColor: colors.paper, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3, minHeight: 48, paddingHorizontal: 12, paddingVertical: 10, fontFamily: fonts.sansRegular, fontSize: 15, color: colors.ink, marginBottom: 7 }, emailLabel: { marginTop: 20 },
  inlineAction: { alignSelf: 'flex-start', minHeight: 44, justifyContent: 'center', paddingHorizontal: 2 }, linkText: { fontFamily: fonts.sans, color: colors.blue, fontSize: 12 }, privacy: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingVertical: 4, marginBottom: 17 },
  copyLink: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.blue, padding: 12, backgroundColor: colors.paperInset, marginTop: 10 },
  action: { minHeight: 48, paddingHorizontal: 15, paddingVertical: 12, gap: 9, backgroundColor: colors.blue, borderRadius: 3, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', marginTop: 10 }, actionText: { fontFamily: fonts.sans, fontSize: 13, lineHeight: 20, color: colors.paperSoft, textAlign: 'center' }, secondaryAction: { backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.paperBorder }, secondaryActionText: { color: colors.blue }, disabled: { opacity: .55 },
  shareIdentity: { borderBottomWidth: 1, borderColor: colors.paperBorder, paddingBottom: 20, marginBottom: 20, gap: 5 }, recipientName: { fontFamily: fonts.display, fontSize: 32, lineHeight: 39, color: colors.ink, marginVertical: 3 }, accepted: { color: colors.green }, footnote: { fontFamily: fonts.sansRegular, fontSize: 10, lineHeight: 16, color: colors.mutedInk, textAlign: 'center', marginTop: 18 },
  empty: { alignItems: 'center', paddingVertical: 43, paddingHorizontal: 12 }, emptyIcon: { width: 64, height: 64, borderRadius: 32, borderColor: colors.paperBorder, borderWidth: 1, justifyContent: 'center', alignItems: 'center', marginBottom: 21 }, emptyTitle: { fontFamily: fonts.display, fontSize: 28, lineHeight: 35, color: colors.ink, textAlign: 'center' }, emptyCopy: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 21, color: colors.mutedInk, textAlign: 'center', marginTop: 11, maxWidth: 300 },
});
