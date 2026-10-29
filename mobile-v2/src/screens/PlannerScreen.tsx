import React from 'react';
import {
  ActivityIndicator, AppState, BackHandler, Clipboard, Linking,
  Platform, RefreshControl, ScrollView, Share, StyleSheet, Text, View, type GestureResponderHandlers,
} from 'react-native';
import * as Crypto from 'expo-crypto';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BottomNav } from '../components/trotter/TrotterKit';
import { WWIcon } from '../components/world-window/WorldWindowUI';
import { PressFeedback, useReducedMotion } from '../components/world-window/motion';
import { ProfileAvatar } from '../components/world-window/profile/ProfileAvatar';
import { headerRowStyle } from '../components/world-window/headerGeometry';
import { IdeaVote } from '../components/world-window/planner/IdeaVote';
import { PlanNotes } from '../components/world-window/planner/PlanNotes';
import { ItineraryDayNav } from '../components/world-window/planner/ItineraryDayNav';
import { ReorderableStops } from '../components/world-window/planner/ReorderableStops';
import { itineraryDayOffset, visibleItineraryDay } from '../components/world-window/planner/itineraryNavigation';
import { PlannerTransportForm, UnscheduledActivities } from '../components/world-window/planner/PlannerResult';
import { plannedActivitySummary, savedIdeaSummary, stayOptionsSummary } from '../components/world-window/planner/plannerResultModel';
import { DreamsForTrip } from '../components/world-window/planner/DreamsForTrip';
import { DreamDestinationField } from '../components/world-window/planner/DreamDestinationField';
import { PeriodGapRow, PeriodPlanForm, StayPicker, StayRow } from '../components/world-window/planner/PlannerDayParts';
import { PlannerAction, PlannerChoices, PlannerField, PlannerGlyph, PlannerPhoto, PlannerSheet, k } from '../components/world-window/planner/PlannerKit';
import { Check, IdeaPicker, ImportDreamsForm, NewIdeaForm, PACES, SetupForm, StopEditor } from '../components/world-window/planner/PlannerForms';
import { canEditPlan, changedDays, clock, dateRange, durationLabel, emptyPlan, formatDay, minutes, openDayPeriods, removeStop, reorderStop, replaceStay, replaceStop, stopForIdea, travelLegLabel, validatePlan, type PlannerPeriodGap } from '../components/world-window/planner/plannerEditing';
import { plannerApi, PlannerApiError, subscribePlannerChanges, type PlannerCreate, type PlannerDay, type PlannerIdea, type PlannerInvitePreview,
  type PlannerDreamScope, type PlannerMember, type PlannerPace, type PlannerPlan, type PlannerRevision, type PlannerStop, type PlannerTrip, type PlannerTripSummary } from '../services/planner';
import { useDreams } from '../services/dreams';
import { getAuthRevision, useTravelTrips } from '../services/travelTrips';
import type { BottomNavTab } from '../data/trotterMock';
import { colors, fonts, layout } from '../theme/trotterTheme';
import { selectionHaptic } from '../utils/experiencePreferences';

type Tab = 'plan' | 'ideas' | 'people';
type Sheet = { kind: 'create' } | { kind: 'settings'; version: number } | { kind: 'transport'; version: number } | { kind: 'destination'; version: number } | { kind: 'import'; ids?: string[] }
  | { kind: 'newIdea' } | { kind: 'idea'; idea: PlannerIdea } | { kind: 'day'; date: string }
  | { kind: 'stop'; stop: PlannerStop; date: string; version: number }
  | { kind: 'pick'; date: string; version: number; replace?: PlannerStop }
  | { kind: 'booking'; date: string; version: number }
  | { kind: 'period'; date: string; gap: PlannerPeriodGap; version: number } | { kind: 'stay'; date: string; version: number }
  | { kind: 'rework'; date?: string } | { kind: 'invite' } | { kind: 'member'; member: PlannerMember } | { kind: 'history' };
const ROLE = { owner: 'Organiser', editor: 'Can edit the plan', contributor: 'Can add ideas & vote' };
const id = () => Crypto.randomUUID();
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : 'Something went wrong. Please try again.';
const liveJob = (trip: PlannerTrip | undefined) => trip?.generation?.status === 'queued' || trip?.generation?.status === 'running';

export type PlannerScreenProps = {
  onTabChange: (tab: BottomNavTab) => void; onOpenProfile: () => void;
  onBackHandlerChange?: (handler: (() => boolean) | null) => void; visible?: boolean;
  initialTripId?: string; initialDreamItemIds?: string[]; initialDestination?: string; initialSourceUrl?: string;
  inviteToken?: string; onInviteConsumed?: () => void;
};

export function PlannerScreen({ onTabChange, onOpenProfile, onBackHandlerChange, visible = true, initialTripId,
  initialDreamItemIds, initialDestination, initialSourceUrl, inviteToken, onInviteConsumed }: PlannerScreenProps) {
  const insets = useSafeAreaInsets(), { accountId } = useTravelTrips(), dreams = useDreams();
  const [trips, setTrips] = React.useState<PlannerTripSummary[]>([]), [tripId, setTripId] = React.useState<string>(), [trip, setTrip] = React.useState<PlannerTrip>();
  const [tab, setTab] = React.useState<Tab>('plan'), [sheet, setSheet] = React.useState<Sheet>(), [draftView, setDraftView] = React.useState(true);
  const [loading, setLoading] = React.useState(true), [refreshing, setRefreshing] = React.useState(false), [busy, setBusy] = React.useState('');
  const [error, setError] = React.useState(''), [notice, setNotice] = React.useState(''), [conflict, setConflict] = React.useState(false);
  const [loadError, setLoadError] = React.useState<{ target: string; message: string }>();
  const [invitation, setInvitation] = React.useState<PlannerInvitePreview>(), [invitationLoading, setInvitationLoading] = React.useState(false), [joined, setJoined] = React.useState(false);
  const [history, setHistory] = React.useState<PlannerRevision[]>([]), [reorderDay, setReorderDay] = React.useState<string>();
  const [optimisticPlan, setOptimisticPlan] = React.useState<{ tripId: string; accountId: typeof accountId; version: number; plan: PlannerPlan; requestId: string }>();
  const [draggingStop, setDraggingStop] = React.useState(false), [reorderError, setReorderError] = React.useState<{ date: string; message: string }>();
  const draggingStopRef = React.useRef(false);
  const [activeDay, setActiveDay] = React.useState<string>(), [dayNavPinned, setDayNavPinned] = React.useState(false), [draftActionHeight, setDraftActionHeight] = React.useState(78);
  const itineraryScroll = React.useRef<ScrollView>(null), dayOffsets = React.useRef<Record<string, number>>({}), dayNavY = React.useRef<number | undefined>(undefined);
  const dayNavHeight = React.useRef(57), scrollY = React.useRef(0), navigationKey = React.useRef('');
  const reducedMotion = useReducedMotion();
  const [pendingSource, setPendingSource] = React.useState<{ tripId: string; url: string; requestId: string }>();
  const alive = React.useRef(true), activeId = React.useRef(tripId), busyRef = React.useRef(false), loadSequence = React.useRef(0), listSequence = React.useRef(0);
  const sheetRef = React.useRef(sheet), visibleRef = React.useRef(visible), owner = React.useRef(accountId), createRequest = React.useRef<{ fingerprint: string; id: string } | undefined>(undefined);
  const generationRequest = React.useRef<{ fingerprint: string; id: string } | undefined>(undefined);
  const ideaRequest = React.useRef<{ fingerprint: string; id: string } | undefined>(undefined);
  activeId.current = tripId; sheetRef.current = sheet; visibleRef.current = visible; owner.current = accountId;
  const valid = (revision: number) => alive.current && getAuthRevision() === revision;
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; loadSequence.current += 1; listSequence.current += 1; }; }, []);

  const update = React.useCallback((value: PlannerTrip) => {
    if (!alive.current) return;
    loadSequence.current += 1;
    if (activeId.current === value.id) setTrip(value);
    setLoadError(current => current?.target === value.id ? undefined : current);
    setTrips(current => [value, ...current.filter(item => item.id !== value.id)].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
  }, []);
  const updateVote = React.useCallback((value: PlannerTrip, ideaId: string) => {
    const voted = value.ideas.find(idea => idea.id === ideaId);
    if (!alive.current || !voted || activeId.current !== value.id) return;
    loadSequence.current += 1;
    // Parallel row votes may finish out of order. Never replace another vote or a newer plan.
    setTrip(current => current?.id === value.id ? { ...current, ideas: current.ideas.map(idea => idea.id === ideaId ? { ...idea, score: voted.score, my_vote: voted.my_vote } : idea) } : current);
  }, []);
  const openTrip = React.useCallback((value: PlannerTrip | string) => {
    const key = typeof value === 'string' ? value : value.id;
    activeId.current = key; setTripId(key); setTrip(typeof value === 'string' ? undefined : value);
    setTab('plan'); setSheet(undefined); setError(''); setNotice(''); setDraftView(true); setJoined(false); setReorderDay(undefined); setReorderError(undefined);
  }, []);
  const loadList = React.useCallback(async (signal?: AbortSignal) => {
    const sequence = ++listSequence.current, revision = getAuthRevision();
    try { const result = await plannerApi.list(signal); if (valid(revision) && sequence === listSequence.current && !signal?.aborted) { setTrips(result.trips); setLoadError(current => current?.target === 'list' ? undefined : current); } }
    catch (cause) { if (valid(revision) && !signal?.aborted && sequence === listSequence.current) setLoadError({ target: 'list', message: errorText(cause) }); }
    finally { if (valid(revision) && sequence === listSequence.current) { setLoading(false); setRefreshing(false); } }
  }, []);
  const loadTrip = React.useCallback(async (key: string, signal?: AbortSignal, quiet = false) => {
    const sequence = ++loadSequence.current, revision = getAuthRevision();
    try {
      const result = await plannerApi.get(key, signal);
      if (!valid(revision) || signal?.aborted || sequence !== loadSequence.current || activeId.current !== key) return;
      setTrip(result); setTrips(current => current.map(item => item.id === key ? result : item));
      setLoadError(current => current?.target === key ? undefined : current);
    } catch (cause) { if (valid(revision) && !signal?.aborted && sequence === loadSequence.current && activeId.current === key && !quiet) setLoadError({ target: key, message: errorText(cause) }); }
    finally { if (valid(revision) && sequence === loadSequence.current) { setLoading(false); setRefreshing(false); } }
  }, []);
  React.useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    if (tripId) void loadTrip(tripId, controller.signal); else void loadList(controller.signal);
    return () => controller.abort();
  }, [visible, tripId, accountId, loadList, loadTrip]);
  React.useEffect(() => {
    if (!visible) return;
    let timer: ReturnType<typeof setTimeout>, disposed = false, foreground = AppState.currentState === 'active', controller: AbortController | undefined;
    const poll = async () => {
      if (disposed) return;
      if (foreground && !busyRef.current && !draggingStopRef.current && activeId.current) { controller = new AbortController(); await loadTrip(activeId.current, controller.signal, true); }
      if (!disposed) timer = setTimeout(() => void poll(), liveJob(trip) ? 2500 : 15000);
    };
    timer = setTimeout(() => void poll(), liveJob(trip) ? 2000 : 15000);
    const subscription = AppState.addEventListener('change', value => { foreground = value === 'active'; });
    return () => { disposed = true; clearTimeout(timer); controller?.abort(); subscription.remove(); };
  }, [visible, tripId, trip?.generation?.status, loadTrip]);
  React.useEffect(() => subscribePlannerChanges(key => {
    if (!visibleRef.current || busyRef.current || draggingStopRef.current) return;
    if (activeId.current && (!key || key === activeId.current)) void loadTrip(activeId.current, undefined, true);
    else if (!activeId.current) void loadList();
  }), [loadTrip, loadList]);
  React.useEffect(() => { if (initialTripId) openTrip(initialTripId); }, [initialTripId, openTrip]);
  const initialSelectionKey = (initialDreamItemIds || []).join(',');
  React.useEffect(() => {
    if (!initialTripId && (initialSelectionKey || initialDestination || initialSourceUrl)) { setSheet({ kind: 'create' }); setError(''); }
  }, [initialTripId, initialSelectionKey, initialDestination, initialSourceUrl]);
  React.useEffect(() => {
    if (!inviteToken) { setInvitation(undefined); setInvitationLoading(false); return; }
    const controller = new AbortController(); setInvitationLoading(true); setError('');
    void plannerApi.previewInvite(inviteToken, controller.signal).then(value => {
      if (alive.current && !controller.signal.aborted) { setInvitation(value); setSheet(undefined); }
    }).catch(cause => { if (alive.current && !controller.signal.aborted) setError(errorText(cause)); })
      .finally(() => { if (alive.current && !controller.signal.aborted) setInvitationLoading(false); });
    return () => controller.abort();
  }, [inviteToken]);
  const closeSheet = () => { setSheet(undefined); setError(''); setConflict(false); };
  const back = React.useCallback(() => {
    if (sheetRef.current) { setSheet(undefined); setError(''); setConflict(false); return true; }
    if (inviteToken) { onInviteConsumed?.(); setInvitation(undefined); setError(''); return true; }
    if (joined) { setJoined(false); return true; }
    if (activeId.current) { activeId.current = undefined; setTripId(undefined); setTrip(undefined); setError(''); setNotice(''); setReorderDay(undefined); return true; }
    return false;
  }, [inviteToken, onInviteConsumed, joined]);
  React.useEffect(() => {
    if (!visible) { onBackHandlerChange?.(null); return; }
    onBackHandlerChange?.(back);
    if (onBackHandlerChange) return () => onBackHandlerChange(null);
    const subscription = BackHandler.addEventListener('hardwareBackPress', back); return () => subscription.remove();
  }, [back, visible, onBackHandlerChange]);

  const run = async (label: string, work: () => Promise<void>) => {
    if (busyRef.current) return;
    const revision = getAuthRevision(); busyRef.current = true; setBusy(label); setError(''); setConflict(false); loadSequence.current += 1;
    try { await work(); }
    catch (cause) {
      if (valid(revision)) {
        setError(errorText(cause));
        if (cause instanceof PlannerApiError && cause.status === 409) { setConflict(true); if (activeId.current) await loadTrip(activeId.current, undefined, true); }
      }
    } finally { if (valid(revision)) setBusy(''); busyRef.current = false; }
  };
  const mutate = (label: string, action: () => Promise<PlannerTrip>, message?: string, close = true) => void run(label, async () => {
    const revision = getAuthRevision(), result = await action(); if (!valid(revision)) return;
    update(result); if (close) setSheet(undefined); if (message) setNotice(message); selectionHaptic('confirmation');
  });
  const openSheet = (value: Sheet) => { if (busyRef.current) return; setSheet(value); setError(''); setNotice(''); setConflict(false); setReorderError(undefined); };
  const savePlan = (plan: PlannerPlan, version: number, message = 'Plan updated.') => {
    if (!trip) return;
    const problem = validatePlan(plan, trip); if (problem) { setError(problem); return; }
    mutate('Saving plan…', () => plannerApi.savePlan(trip.id, version, plan), message);
  };
  const currentPlan = optimisticPlan && optimisticPlan.tripId === trip?.id && optimisticPlan.accountId === accountId && optimisticPlan.version === trip?.version
    ? optimisticPlan.plan : trip?.plan ?? (trip ? emptyPlan(trip) : undefined);
  const reorderPlan = (date: string, stopId: string, offset: number) => {
    if (!trip || !currentPlan || busyRef.current || !offset || !canEditPlan(trip.role)) return false;
    try {
      const plan = reorderStop(currentPlan, date, stopId, offset), problem = validatePlan(plan, trip);
      if (problem) throw new Error(problem);
      if (JSON.stringify(plan) === JSON.stringify(currentPlan)) return false;
      const requestId = id(), revision = getAuthRevision(), key = trip.id, version = trip.version;
      setReorderError(undefined);
      setOptimisticPlan({ tripId: key, accountId, version, plan, requestId });
      void run('Saving order…', async () => {
        try {
          const result = await plannerApi.savePlan(key, version, plan);
          if (valid(revision) && activeId.current === key) { update(result); selectionHaptic('confirmation'); }
        } catch (cause) {
          if (valid(revision) && activeId.current === key) setReorderError({ date, message: cause instanceof PlannerApiError && cause.status === 409
            ? 'Someone updated the plan. The latest order is being loaded; try your change again.'
            : 'This order could not be saved. Your previous order has been restored. Try again.' });
          throw cause;
        } finally {
          if (alive.current) setOptimisticPlan(value => value?.requestId === requestId ? undefined : value);
        }
      });
      return true;
    } catch (cause) { setReorderError({ date, message: errorText(cause) }); return false; }
  };
  const tripIdeaIds = React.useMemo(() => new Set(trip?.ideas.map(idea => idea.id) ?? []), [trip?.ideas]);
  const tripIdeaCategories = React.useMemo(() => new Map(trip?.ideas.map(idea => [idea.id, idea.category]) ?? []), [trip?.ideas]);
  const generate = (day?: string, pace?: PlannerPace) => {
    if (!trip) return;
    const fingerprint = JSON.stringify([trip.id, trip.version, day, pace]);
    if (generationRequest.current?.fingerprint !== fingerprint) generationRequest.current = { fingerprint, id: id() };
    void run('Starting your plan…', async () => {
      const revision = getAuthRevision(), job = await plannerApi.generate(trip.id, { expected_version: trip.version, client_request_id: generationRequest.current!.id, day, pace, mode: 'ai' });
      if (!valid(revision)) return;
      update({ ...trip, generation: job }); setSheet(undefined); setTab('plan'); setDraftView(true);
      setNotice('Your draft is being prepared. You can keep browsing.');
    });
  };
  const create = (values: Omit<PlannerCreate, 'client_request_id'>) => {
    const fingerprint = JSON.stringify([values, initialSourceUrl]);
    if (createRequest.current?.fingerprint !== fingerprint) createRequest.current = { fingerprint, id: id() };
    void run('Creating trip…', async () => {
      const revision = getAuthRevision(); let created = await plannerApi.create({ ...values, client_request_id: createRequest.current!.id });
      if (!valid(revision)) return;
      createRequest.current = undefined;
      openTrip(created); update(created); setTab('ideas');
      if (initialSourceUrl) {
        const source = { tripId: created.id, url: initialSourceUrl, requestId: id() }; setPendingSource(source);
        created = await plannerApi.addSource(created.id, { source_url: source.url, client_request_id: source.requestId });
        if (!valid(revision)) return;
        update(created); setPendingSource(undefined);
      }
      setNotice(values.dream_item_ids?.length ? 'Your selected places are ready in Ideas.' : 'Add a few ideas, then make your plan.');
    });
  };
  const addIdea = (values: { title: string; category: string; city: string; country: string; duration_minutes: number } | { source_url: string }) => {
    if (!trip) return;
    const fingerprint = JSON.stringify([trip.id, values]);
    if (ideaRequest.current?.fingerprint !== fingerprint) ideaRequest.current = { fingerprint, id: id() };
    const requestId = ideaRequest.current.id;
    mutate('Adding to Ideas…', async () => {
      const result = 'source_url' in values ? await plannerApi.addSource(trip.id, { ...values, client_request_id: requestId })
        : await plannerApi.addIdea(trip.id, { ...values, client_request_id: requestId });
      ideaRequest.current = undefined; return result;
    }, 'source_url' in values ? 'Your link is in Ideas. Places will appear as it is processed.' : 'Place added to Ideas.');
  };
  const displayedPlan = trip?.draft && draftView ? trip.draft.plan : currentPlan;
  const editing = trip && canEditPlan(trip.role), viewingDraft = Boolean(trip?.draft && draftView);
  const displayDays = displayedPlan?.days ?? [], pendingInvites = trip?.invites.filter(value => value.status === 'pending' || value.status === 'active') ?? [];
  const showDayNav = !!trip && tab === 'plan' && !inviteToken && !joined && !!(trip.plan || trip.draft) && displayDays.length > 1;
  const showDraftAction = !!trip && !!editing && viewingDraft && tab === 'plan' && !inviteToken && !joined;
  const dates = displayDays.map(day => day.date);
  const nextNavigationKey = `${accountId}:${tripId}:${tab}:${viewingDraft ? trip?.draft?.id : 'plan'}:${dates.join(',')}`;
  if (navigationKey.current !== nextNavigationKey) {
    navigationKey.current = nextNavigationKey; dayOffsets.current = {}; dayNavY.current = undefined; scrollY.current = 0;
  }
  React.useEffect(() => { setActiveDay(undefined); setDayNavPinned(false); }, [nextNavigationKey]);
  const trackItinerary = (y: number) => {
    scrollY.current = y;
    const pinned = showDayNav && dayNavY.current !== undefined && y >= dayNavY.current;
    setDayNavPinned(pinned);
    setActiveDay(visibleItineraryDay(dates, dayOffsets.current, y, pinned ? dayNavHeight.current : 0));
  };
  const jumpToDay = (date: string) => {
    const y = itineraryDayOffset(dayOffsets.current[date], dayNavHeight.current);
    if (y === undefined) return;
    setActiveDay(date); itineraryScroll.current?.scrollTo({ y, animated: !reducedMotion });
  };
  const refresh = () => { setRefreshing(true); setError(''); if (tripId) void loadTrip(tripId); else void loadList(); };
  const safeSource = async (url: string) => { try { const parsed = new URL(url); if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) throw new Error(); await Linking.openURL(parsed.toString()); } catch { setError('This link could not be opened.'); } };

  return <View style={[s.screen, { paddingTop: insets.top }]}>
    <View style={s.header}>
      {tripId || inviteToken || joined ? <PressFeedback style={s.back} onPress={back} accessibilityRole="button" accessibilityLabel="Back to planner"><WWIcon name="back" size={21} /><Text style={s.backText}>Planner</Text></PressFeedback>
        : <Text style={s.brand}>Trotter</Text>}
      <ProfileAvatar onPress={onOpenProfile} />
    </View>
    <View style={{ flex: 1 }}>
    <ScrollView key={nextNavigationKey} ref={itineraryScroll} scrollEnabled={!draggingStop} onScroll={event => trackItinerary(event.nativeEvent.contentOffset.y)} scrollEventThrottle={32}
      keyboardShouldPersistTaps="handled" showsVerticalScrollIndicator={false} contentContainerStyle={[s.content, { paddingBottom: insets.bottom + layout.bottomNavHeight + 36 + (showDraftAction ? draftActionHeight : 0) }]}
      refreshControl={!inviteToken && !joined ? <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.ink} /> : undefined}>
      {!sheet && !inviteToken && loadError?.target === (tripId || 'list') ? <View style={s.feedback}><Text style={k.error} accessibilityRole="alert">{loadError.message}</Text><PlannerAction label="Retry" quiet onPress={refresh} disabled={!!busy} /></View> : null}
      {!sheet && error && !reorderError ? <View style={s.feedback}><Text style={k.error} accessibilityRole="alert">{error}</Text>
        {conflict ? <PlannerAction label="Review latest plan" secondary onPress={() => { setError(''); setConflict(false); setDraftView(false); }} />
          : !inviteToken ? <PlannerAction label="Retry" quiet onPress={refresh} disabled={!!busy} /> : null}</View> : null}
      {!sheet && notice ? <Text style={s.notice} accessibilityLiveRegion="polite">{notice}</Text> : null}
      {!sheet && busy && busy !== 'Saving order…' ? <View style={s.loadingRow}><ActivityIndicator color={colors.ink} size="small" /><Text style={k.hint}>{busy}</Text></View> : null}
      {pendingSource && pendingSource.tripId === tripId ? <PlannerAction label="Retry adding your Instagram link" secondary disabled={!!busy} onPress={() => mutate('Adding link…', async () => {
        const result = await plannerApi.addSource(pendingSource.tripId, { source_url: pendingSource.url, client_request_id: pendingSource.requestId }); setPendingSource(undefined); return result;
      }, 'Your link is in Ideas.')} /> : null}

      {inviteToken ? <>
        {invitationLoading ? <Loading label="Opening your invitation…" /> : invitation ? <View style={s.invitation}>
          <View style={s.inviteCover}><PlannerPhoto uri={invitation.trip.cover_image_url} country={invitation.trip.destination} cover title={invitation.trip.destination} /></View>
          <Text style={[k.body, { textAlign: 'center' }]}>{invitation.inviter_name} invited you</Text>
          <Text style={[s.title, { textAlign: 'center' }]}>{invitation.trip.title}</Text>
          <Text style={[k.body, { textAlign: 'center' }]}>{dateRange(invitation.trip.start_date, invitation.trip.end_date)}</Text>
          <Text style={s.invitationCopy}>Bring your places.{"\n"}Make a plan together.</Text>
          <PlannerAction label="Join trip" busy={!!busy} onPress={() => void run('Joining trip…', async () => {
            const revision = getAuthRevision(), wasMember = trips.some(value => value.id === invitation.trip.id), result = await plannerApi.acceptInvite(inviteToken);
            if (!valid(revision)) return;
            openTrip(result); update(result); setJoined(!wasMember); onInviteConsumed?.(); selectionHaptic('confirmation');
          })} />
          <Text style={[k.hint, { textAlign: 'center' }]}>{invitation.role === 'editor' ? 'You can add ideas, vote and edit the plan.' : 'You can add ideas and vote.'}</Text>
          <PlannerAction label="Maybe later" quiet onPress={() => { onInviteConsumed?.(); setInvitation(undefined); }} />
          <Text style={[k.hint, { textAlign: 'center' }]}>Your personal Dreams stay private.</Text>
        </View> : <View style={s.empty}><Text style={s.sectionTitle}>Invitation unavailable</Text><Text style={k.body}>Ask the organiser for a fresh invitation link.</Text><PlannerAction label="Back to your trips" secondary onPress={() => onInviteConsumed?.()} /></View>}
      </> : joined && trip ? <View style={s.invitation}>
        <View style={s.inviteCover}><PlannerPhoto uri={trip.cover_image_url} country={trip.destination} cover title={trip.destination} /></View>
        <Text style={s.title}>You’re coming to {trip.destination}</Text><Text style={k.body}>{trip.title} · {dateRange(trip.start_date, trip.end_date)}</Text>
        <Text style={[k.body, { marginVertical: 12 }]}>Add your ideas. Help shape the days.</Text>
        <PlannerAction label="Explore trip" onPress={() => setJoined(false)} />
        <PlannerAction label="Add your saved places" secondary onPress={() => { setJoined(false); openSheet({ kind: 'import' }); }} />
        <Text style={k.hint}>Choose what to share from your Dreams.</Text>
      </View> : !tripId ? <>
        <View style={s.homeHeading}><Text style={s.title}>{trips.length ? 'Your trips' : 'Your next trip'}</Text><Text style={k.body}>Choose a destination, bring in saved places and invite your people.</Text></View>
        <PlannerAction label="Plan a trip" icon="plus" prominent onPress={() => openSheet({ kind: 'create' })} disabled={!!busy} />
        {loading ? <Loading label="Gathering your trips…" /> : trips.length ? <View style={s.tripList}>{trips.map(value => <PressFeedback key={value.id} disabled={!!busy} accessibilityRole="button" accessibilityLabel={`Open ${value.title}`} onPress={() => openTrip(value.id)} style={s.tripCard}>
          <View style={s.cardCover}><PlannerPhoto uri={value.cover_image_url} country={value.destination} cover title={value.destination} /></View>
          <View style={s.cardCaption}><Text style={s.cardTitle}>{value.title}</Text><Text style={k.hint}>{dateRange(value.start_date, value.end_date)} · {value.member_count} {value.member_count === 1 ? 'traveller' : 'travellers'}</Text>
            <Text style={[k.hint, { paddingTop: 5 }]}>{value.idea_count} {value.idea_count === 1 ? 'idea' : 'ideas'}</Text></View>
        </PressFeedback>)}</View> : null}
      </> : !trip ? <Loading label="Opening your trip…" /> : <>
        <View style={s.tripHeading}><View style={{ flex: 1 }}><Text style={s.title}>{trip.title}</Text><Text style={k.body}>{dateRange(trip.start_date, trip.end_date)} · {trip.member_count} {trip.member_count === 1 ? 'traveller' : 'travellers'}</Text></View>
          {editing ? <PressFeedback style={k.iconButton} onPress={() => openSheet({ kind: 'settings', version: trip.version })} accessibilityRole="button" accessibilityLabel="Trip details"><WWIcon name="settings" size={18} /></PressFeedback> : null}
        </View>
        <View style={s.tabs} accessibilityRole="tablist">{(['plan', 'ideas', 'people'] as const).map(key => <PressFeedback key={key} style={[s.tab, tab === key && s.selectedTab]} onPress={() => { setTab(key); setError(''); setNotice(''); }} accessibilityRole="tab" accessibilityState={{ selected: tab === key }}>
          <Text style={[s.tabText, tab === key && s.selectedTabText]}>{key[0].toUpperCase() + key.slice(1)}</Text></PressFeedback>)}</View>

        {tab === 'ideas' ? <>
          <View style={s.sectionRow}><Text style={[k.body, { flex: 1 }]}>{savedIdeaSummary(trip.ideas)}</Text><PlannerAction label="Add" icon="plus" quiet onPress={() => openSheet({ kind: 'newIdea' })} disabled={!!busy} /></View>
          <DreamsForTrip key={`${accountId}:${trip.id}:${trip.match_scope?.id || ''}`} trip={trip} visible={visible && !sheet} dreamsRevision={dreams.items} compact={trip.ideas.length > 0}
            onChanged={() => { if (visibleRef.current && activeId.current === trip.id) void loadTrip(trip.id); }} onChooseDestination={editing ? () => openSheet({ kind: 'destination', version: trip.version }) : undefined}
            onBrowseDreams={() => openSheet({ kind: 'import' })} />
          {trip.ideas.map(idea => <View key={idea.id} style={s.ideaRow}>
              <PressFeedback style={s.ideaContent} accessibilityRole="button" accessibilityLabel={`Open ${idea.title}`} disabled={!!busy} onPress={() => openSheet({ kind: 'idea', idea })}>
                <View style={s.ideaPhoto}><PlannerPhoto uri={idea.image_url} category={idea.category} title={idea.title} /></View>
                <View style={s.ideaCopy}><Text style={s.placeTitle} numberOfLines={2}>{idea.title}</Text><Text style={s.metadata} numberOfLines={2}>{[idea.city || idea.country, contributorLabel(idea)].filter(Boolean).join(' · ')}</Text>
                  {idea.status !== 'ready' ? <Text style={s.statusText}>{idea.status === 'processing' ? 'Finding places…' : 'Details to confirm'}</Text> : null}</View>
              </PressFeedback>
              <IdeaVote tripId={trip.id} idea={idea} disabled={!!busy} onUpdate={updateVote} onError={setError} />
            </View>)}
          {editing && trip.ideas.length > 0 ? <PlannerAction label={trip.plan ? 'Review ideas & rework plan' : 'Plan this trip'} prominent secondary={!!trip.plan} onPress={() => openSheet({ kind: 'rework' })} disabled={!!busy || liveJob(trip)} style={{ marginTop: 20 }} /> : null}
        </> : tab === 'people' ? <>
          <View style={s.sectionRow}><Text style={s.sectionTitle}>Who’s coming?</Text>{trip.role === 'owner' ? <PlannerAction label="Invite" icon="plus" quiet onPress={() => openSheet({ kind: 'invite' })} disabled={!!busy} /> : null}</View>
          <Text style={[k.hint, { marginBottom: 10 }]}>Joined · {trip.members.length}</Text>
          {trip.members.map((member, index) => <PressFeedback key={member.user_id} style={s.member} disabled={trip.role !== 'owner' || member.role === 'owner' || !!busy} onPress={() => openSheet({ kind: 'member', member })} accessibilityRole="button" accessibilityLabel={`${member.name}, ${ROLE[member.role]}`}>
            <View style={[s.memberAvatar, { backgroundColor: ['#d7e0dd', '#e5cdb9', '#d5ddca', '#e4ddd1'][index % 4] }]}><Text style={s.memberInitial}>{member.name.slice(0, 1).toUpperCase()}</Text></View>
            <View style={{ flex: 1 }}><Text style={s.memberName}>{member.name}{String(accountId) === String(member.user_id) ? ' (you)' : ''}</Text><Text style={k.hint}>{ROLE[member.role]}</Text></View>
            {trip.role === 'owner' && member.role !== 'owner' ? <WWIcon name="chevron" size={16} /> : null}</PressFeedback>)}
          {trip.role === 'owner' && pendingInvites.length ? <View style={{ marginTop: 26 }}><Text style={k.label}>Invitations · {pendingInvites.length}</Text>
            {pendingInvites.map(invite => <View key={invite.id} style={s.inviteRow}><View style={{ flex: 1 }}><Text style={s.memberName}>{invite.label || 'Invite link'}</Text><Text style={k.hint}>{invite.uses ? `${invite.uses} joined · ` : ''}Expires {formatDay(invite.expires_at.slice(0, 10))}</Text></View>
              <PlannerAction label="Revoke" quiet disabled={!!busy} onPress={() => mutate('Revoking invitation…', () => plannerApi.revoke(trip.id, invite.id), 'This invitation can no longer be used.')} /></View>)}</View> : null}
          {trip.role !== 'owner' ? <LeaveTrip busy={!!busy} onLeave={() => void run('Leaving trip…', async () => { await plannerApi.removeMember(trip.id, String(accountId)); if (!alive.current) return; back(); setTrips(current => current.filter(value => value.id !== trip.id)); })} /> : null}
        </> : <>
          {liveJob(trip) ? <View style={s.job}><ActivityIndicator color={colors.ink} size="small" /><View style={{ flex: 1 }}><Text style={k.label}>Shaping your days…</Text><Text style={k.hint}>{trip.generation?.message || 'Your current plan stays in place while the draft is prepared.'}</Text></View></View> : trip.generation?.status === 'failed' ? <View style={s.feedback}><Text style={k.body}>{trip.generation.message || 'The draft could not be prepared. Your plan is unchanged.'}</Text>{editing ? <PlannerAction label="Try again" quiet onPress={() => { generationRequest.current = undefined; openSheet({ kind: 'rework' }); }} /> : null}</View> : null}
          {trip.draft ? <View style={s.draftNotice}><View style={s.sectionRow}><Text style={s.draftLabel}>{viewingDraft ? 'Draft itinerary' : 'Your current plan'}</Text>
            {trip.plan ? <PlannerAction label={viewingDraft ? 'View current' : 'View draft'} quiet onPress={() => setDraftView(value => !value)} /> : null}</View>
            {viewingDraft ? <><Text style={k.body}>{plannedActivitySummary(trip.draft.plan, trip.ideas)}</Text><Text style={k.hint}>{stayOptionsSummary(trip.ideas)} · Check each night below.</Text><Text style={k.hint}>{changedDays(trip.plan, trip.draft.plan).length} {changedDays(trip.plan, trip.draft.plan).length === 1 ? 'day' : 'days'} {trip.plan ? 'updated' : 'planned'} · Review before using this plan.</Text></> : null}
          </View> : null}
          {showDayNav ? <View pointerEvents={dayNavPinned ? 'none' : 'auto'} accessibilityElementsHidden={dayNavPinned} importantForAccessibility={dayNavPinned ? 'no-hide-descendants' : 'auto'}
            onLayout={event => { dayNavY.current = event.nativeEvent.layout.y; dayNavHeight.current = event.nativeEvent.layout.height; trackItinerary(scrollY.current); }}>
            <ItineraryDayNav dates={dates} active={activeDay || dates[0]} onSelect={jumpToDay} />
          </View> : null}
          {!trip.plan && !trip.draft && !liveJob(trip) ? <View style={s.empty}><Text style={s.sectionTitle}>Start your plan</Text><Text style={k.body}>{trip.ideas.length ? 'Build a draft from your saved places, dates and pace, then edit each day.' : 'Share saved places from your Dreams in Ideas, then build your itinerary.'}</Text>
            {editing ? <PlannerAction label={trip.ideas.length ? 'Plan this trip' : 'Choose some ideas'} prominent onPress={() => trip.ideas.length ? openSheet({ kind: 'rework' }) : setTab('ideas')} disabled={!!busy} /> : <Text style={k.hint}>An organiser or editor can create the itinerary.</Text>}
            {editing ? <PlannerAction label="Start planning by hand" quiet onPress={() => savePlan(emptyPlan(trip), trip.version, 'Your days are ready. Add a place to begin.')} /> : null}
          </View> : displayDays.map((day, index) => <View key={day.date} style={s.day} onLayout={event => { dayOffsets.current[day.date] = event.nativeEvent.layout.y; trackItinerary(scrollY.current); }}>
            <View style={s.dayHeading}><View style={{ flex: 1 }}><Text style={s.dayTitle}>Day {index + 1} <Text style={s.dayDate}>· {formatDay(day.date)}</Text></Text></View>
              {editing && !viewingDraft ? <PlannerAction label={reorderDay === day.date ? 'Done' : 'Edit day'} quiet disabled={!!busy} onPress={() => reorderDay === day.date ? setReorderDay(undefined) : openSheet({ kind: 'day', date: day.date })} /> : null}</View>
            {day.planning_note ? <Text style={[k.hint, { marginBottom: 8 }]}>{day.planning_note}</Text> : null}
            {reorderDay === day.date ? <Text accessibilityLiveRegion="polite" style={[k.hint, { marginBottom: 10, minHeight: 36 }]}>{busy === 'Saving order…' ? 'Saving order…' : 'Drag a handle to reorder. Locked stops keep their time.'}</Text> : null}
            {reorderError?.date === day.date ? <Text accessibilityRole="alert" style={[k.error, { marginBottom: 12 }]}>{reorderError.message}</Text> : null}
            {reorderDay === day.date && !viewingDraft ? <ReorderableStops stops={day.stops} enabled={!!editing && !busy && visible && !sheet} onDragging={value => {
              draggingStopRef.current = value; setDraggingStop(value); if (value) { loadSequence.current += 1; setReorderError(undefined); }
            }}
              onReorder={(stopId, offset) => reorderPlan(day.date, stopId, offset)} renderStop={(stop, handle) => <StopRow stop={stop} idea={trip.ideas.find(idea => idea.id === stop.idea_id)}
                editable={!!editing && !busy} handle={handle} onPress={() => openSheet({ kind: 'stop', stop, date: day.date, version: trip.version })} />} />
              : [...day.stops.map(stop => ({ stop, time: minutes(stop.start_time) })), ...openDayPeriods(displayedPlan!, day.date, trip.transport_modes?.length ? trip.transport_modes : [trip.transport], tripIdeaIds, tripIdeaCategories).map(gap => ({ gap, time: minutes(gap.start_time) }))]
              .sort((a, b) => a.time - b.time).map(entry => 'gap' in entry ? <PeriodGapRow key={`gap-${entry.gap.label}`} gap={entry.gap}
                onPress={editing && !viewingDraft && !busy ? () => openSheet({ kind: 'period', date: day.date, gap: entry.gap, version: trip.version }) : undefined} />
                : <StopRow key={entry.stop.id} stop={entry.stop} idea={trip.ideas.find(idea => idea.id === entry.stop.idea_id)} travelLabel={travelLegLabel(day, entry.stop, trip.transport_modes?.length ? trip.transport_modes : [trip.transport], tripIdeaIds)}
                  editable={!!editing && !viewingDraft && !busy}
                  onPress={() => openSheet({ kind: 'stop', stop: entry.stop, date: day.date, version: trip.version })} />)}
            {index < displayDays.length - 1 || (day.stay && day.stay.status !== 'not_needed') ? <StayRow stay={day.stay} ideas={trip.ideas}
              onPress={editing && !viewingDraft && !busy ? () => openSheet({ kind: 'stay', date: day.date, version: trip.version }) : undefined} /> : null}
          </View>)}
          {displayedPlan ? <PlanNotes warnings={displayedPlan.warnings} /> : null}
          {displayedPlan ? <UnscheduledActivities key={trip.draft && viewingDraft ? trip.draft.id : `${trip.id}:plan`} plan={displayedPlan} ideas={trip.ideas}
            modes={trip.transport_modes?.length ? trip.transport_modes : [trip.transport]}
            onIdea={idea => openSheet({ kind: 'idea', idea })} onTransport={editing && !busy ? () => openSheet({ kind: 'transport', version: trip.version }) : undefined} /> : null}
          {editing && viewingDraft && trip.draft ? <View style={s.planActions}>
            <PlannerAction label="Discard draft" quiet disabled={!!busy} onPress={() => mutate('Discarding draft…', () => plannerApi.discardDraft(trip.id, trip.version), 'Draft discarded.')} /></View>
            : trip.plan && editing ? <View style={s.planActions}><PlannerAction label="Rework the trip" secondary disabled={!!busy || liveJob(trip)} onPress={() => openSheet({ kind: 'rework' })} />
              <PlannerAction label="Previous versions" quiet disabled={!!busy} onPress={() => { openSheet({ kind: 'history' }); setHistory([]); void run('Loading versions…', async () => { const result = await plannerApi.history(trip.id); if (alive.current) setHistory(result.revisions); }); }} /></View> : null}
        </>}
      </>}
    </ScrollView>
    {showDayNav && dayNavPinned ? <View style={s.pinnedDayNav}><ItineraryDayNav dates={dates} active={activeDay || dates[0]} onSelect={jumpToDay} /></View> : null}
    </View>
    {showDraftAction && trip?.draft ? <View style={[s.draftActionDock, { bottom: layout.bottomNavHeight + insets.bottom }]} onLayout={event => setDraftActionHeight(event.nativeEvent.layout.height)}>
      <View style={s.draftActionInner}><PlannerAction label="Use this plan" busy={busy === 'Saving your plan…'} disabled={!!busy || !visible}
        onPress={() => mutate('Saving your plan…', () => plannerApi.acceptDraft(trip.id, trip.version, trip.draft!.id), 'This is now your trip plan.')} /></View>
    </View> : null}
    <BottomNav active={'planner' as BottomNavTab} onChange={onTabChange} />

    {sheet ? <PlannerSheet visible={visible} transitionKey={JSON.stringify([sheet.kind, 'date' in sheet ? sheet.date : null, 'stop' in sheet ? sheet.stop.id : null, 'idea' in sheet ? sheet.idea.id : null, 'member' in sheet ? sheet.member.user_id : null])} title={sheetTitle(sheet)} subtitle={sheet.kind === 'create' ? 'Start with the essentials.' : sheet.kind === 'import' ? trip?.title : undefined} onClose={closeSheet} busy={!!busy} error={error}>
      {conflict && trip ? <View style={s.feedback}><Text style={k.body}>A newer version has been loaded. Your entered values are still here.</Text><PlannerAction label="Use the latest version as my starting point" secondary onPress={() => {
        setSheet(current => current && 'version' in current ? { ...current, version: trip.version } : current); setConflict(false); setError(''); setNotice('Review your changes, then save.');
      }} /></View> : null}
      {sheet.kind === 'create' ? <><SetupForm active={visible} destination={initialDestination} initialIds={initialDreamItemIds} busy={!!busy} onSubmit={create} />{initialSourceUrl ? <Text style={[k.hint, { marginTop: 12 }]}>Your Instagram link will be added to this trip’s Ideas.</Text> : null}</> : null}
      {sheet.kind === 'destination' && trip ? <ConnectDestination trip={trip} active={visible} busy={!!busy} onSubmit={scope => mutate('Finding your saved places…', () => plannerApi.update(trip.id, { match_scope_id: scope.id, expected_version: sheet.version }))} /> : null}
      {sheet.kind === 'transport' && trip ? <PlannerTransportForm modes={trip.transport_modes?.length ? trip.transport_modes : [trip.transport]} busy={!!busy}
        onSave={modes => mutate('Saving travel options…', () => plannerApi.update(trip.id, { transport: modes[0], transport_modes: modes, expected_version: sheet.version }), 'Travel options saved. Rework the trip when you’re ready.')} /> : null}
      {sheet.kind === 'settings' && trip ? <><SetupForm trip={trip} active={visible} busy={!!busy} onSubmit={values => mutate('Updating trip…', () => plannerApi.update(trip.id, { ...values, expected_version: sheet.version }), 'Trip details updated.')} />
        {trip.role === 'owner' ? <DeleteTrip busy={!!busy} onDelete={() => void run('Deleting trip…', async () => {
          const revision = getAuthRevision(); await plannerApi.removeTrip(trip.id, sheet.version); if (!valid(revision)) return;
          activeId.current = undefined; setTripId(undefined); setTrip(undefined); setSheet(undefined); setTrips(current => current.filter(value => value.id !== trip.id)); setNotice('Trip deleted.');
        })} /> : null}</> : null}
      {sheet.kind === 'import' && trip ? <ImportDreamsForm items={dreams.items} initialIds={sheet.ids} destination={trip.destination} busy={!!busy} onSubmit={ids => mutate('Adding your places…', () => plannerApi.importDreams(trip.id, ids), 'Your selected places are in Ideas.')} /> : null}
      {sheet.kind === 'newIdea' && trip ? <><PlannerAction label="Choose from your Dreams" secondary disabled={!!busy} onPress={() => openSheet({ kind: 'import' })} style={{ marginBottom: 20 }} />
        <NewIdeaForm country={trip.destination} busy={!!busy} onSubmit={addIdea} onSource={source_url => addIdea({ source_url })} /></> : null}
      {sheet.kind === 'idea' && trip ? <IdeaDetails idea={trip.ideas.find(value => value.id === sheet.idea.id) || sheet.idea} editable={!!editing || String(sheet.idea.created_by) === String(accountId)} busy={!!busy}
        onSource={safeSource} onUpdate={values => mutate('Updating idea…', () => plannerApi.updateIdea(trip.id, sheet.idea.id, values), 'Idea updated.')}
        onRemove={() => mutate('Removing idea…', () => plannerApi.removeIdea(trip.id, sheet.idea.id), 'Idea removed.')}
        onAddToPlan={editing && currentPlan ? () => {
          const existingDay = currentPlan.days.find(day => day.stops.some(stop => stop.idea_id === sheet.idea.id));
          const day = existingDay || currentPlan.days[0], idea = trip.ideas.find(value => value.id === sheet.idea.id) || sheet.idea;
          const stop = existingDay?.stops.find(value => value.idea_id === idea.id) || stopForIdea(idea, id(), day);
          openSheet({ kind: 'stop', stop, date: day.date, version: trip.version });
        } : undefined} /> : null}
      {sheet.kind === 'day' && trip ? <><Text style={[k.body, { marginBottom: 12 }]}>{formatDay(sheet.date, { weekday: 'long' })}</Text>
        <PlannerAction label="Add a place from Ideas" quiet icon="plus" onPress={() => openSheet({ kind: 'pick', date: sheet.date, version: trip.version })} />
        <PlannerAction label="Reorder stops" quiet onPress={() => { setReorderDay(sheet.date); closeSheet(); }} />
        <PlannerAction label="Add a booking or a break" quiet onPress={() => openSheet({ kind: 'booking', date: sheet.date, version: trip.version })} />
        <PlannerAction label="Accommodation for this night" quiet onPress={() => openSheet({ kind: 'stay', date: sheet.date, version: trip.version })} />
        <PlannerAction label="Rework this day" secondary disabled={liveJob(trip)} onPress={() => openSheet({ kind: 'rework', date: sheet.date })} style={{ marginTop: 16 }} /></> : null}
      {sheet.kind === 'period' && trip && currentPlan ? <PeriodPlanForm gap={sheet.gap} ideas={trip.ideas} plan={currentPlan} busy={!!busy}
        onPlace={idea => { const day = currentPlan.days.find(day => day.date === sheet.date)!; openSheet({ kind: 'stop', date: sheet.date, version: sheet.version, stop: { ...stopForIdea(idea, id(), day), start_time: sheet.gap.start_time } }); }}
        onText={value => { const stop = { ...value, id: id() }; savePlan(replaceStop(currentPlan, stop.id, sheet.date, stop), sheet.version); }} /> : null}
      {sheet.kind === 'stay' && trip && currentPlan ? <StayPicker ideas={trip.ideas} stay={currentPlan.days.find(day => day.date === sheet.date)?.stay} busy={!!busy}
        onChoose={stay => savePlan(replaceStay(currentPlan, sheet.date, stay), sheet.version, 'Accommodation updated.')} /> : null}
      {sheet.kind === 'stop' && trip && currentPlan ? <StopEditor stop={sheet.stop} date={sheet.date} days={currentPlan.days} busy={!!busy}
        onSave={(stop, date) => { try { savePlan(replaceStop(currentPlan, sheet.stop.id, date, stop), sheet.version); } catch (cause) { setError(errorText(cause)); } }}
        onRemove={() => { try { savePlan(removeStop(currentPlan, sheet.stop.id), sheet.version, 'Stop removed. You can restore it from Previous versions.'); } catch (cause) { setError(errorText(cause)); } }}
        onSwap={() => openSheet({ kind: 'pick', date: sheet.date, version: sheet.version, replace: sheet.stop })}
        onMove={offset => { try { savePlan(reorderStop(currentPlan, sheet.date, sheet.stop.id, offset), sheet.version); } catch (cause) { setError(errorText(cause)); } }} /> : null}
      {sheet.kind === 'pick' && trip && currentPlan ? <IdeaPicker ideas={trip.ideas} plan={trip.plan} busy={!!busy} onChoose={idea => {
        const day = currentPlan.days.find(value => value.date === sheet.date)!;
        const stop = sheet.replace ? { ...sheet.replace, idea_id: idea.id, title: idea.title, duration_minutes: idea.duration_minutes || 60, travel_minutes: undefined, travel_source: 'unknown' as const, travel_from_stop_id: undefined, travel_mode: undefined, travel_blocked: undefined }
          : stopForIdea(idea, id(), day);
        openSheet({ kind: 'stop', stop, date: sheet.date, version: sheet.version });
      }} /> : null}
      {sheet.kind === 'booking' && trip && currentPlan ? <><BookingImport trip={trip} busy={!!busy} onImport={ids => mutate('Adding bookings…', () => plannerApi.importBookings(trip.id, sheet.version, ids), 'Bookings added and locked in your plan.')} /><BookingForm busy={!!busy} onSubmit={stop => savePlan(replaceStop(currentPlan, stop.id, sheet.date, stop), sheet.version)} /></> : null}
      {sheet.kind === 'rework' && trip ? <ReworkForm trip={trip} date={sheet.date} busy={!!busy} onGenerate={pace => generate(sheet.date, pace)} /> : null}
      {sheet.kind === 'invite' && trip ? <InviteForm trip={trip} busy={!!busy} run={run} /> : null}
      {sheet.kind === 'member' && trip ? <MemberForm member={sheet.member} busy={!!busy} onRole={role => mutate('Updating access…', () => plannerApi.changeRole(trip.id, sheet.member.user_id, role), 'Access updated.')}
        onRemove={() => mutate('Removing member…', () => plannerApi.removeMember(trip.id, sheet.member.user_id), 'This person no longer has access to the trip.')} /> : null}
      {sheet.kind === 'history' && trip ? <>{!history.length ? <Text style={k.body}>{busy ? 'Loading earlier plans…' : 'Earlier versions appear here after your first edit.'}</Text> : history.map((revision, index) => <View key={revision.id} style={s.historyRow}>
        <View style={{ flex: 1 }}><Text style={s.memberName}>{revision.source === 'ai' ? 'Suggested itinerary' : revision.source === 'restore' ? 'Restored plan' : 'Plan version'}</Text><Text style={k.hint}>{new Date(revision.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })} · {revision.plan.days.reduce((sum, day) => sum + day.stops.length, 0)} stops</Text></View>
        <PlannerAction label="Restore" quiet disabled={!!busy} onPress={() => mutate('Restoring plan…', () => plannerApi.restore(trip.id, trip.version, revision.id), 'Earlier plan restored. Your later versions remain in history.')} /></View>)}</> : null}
    </PlannerSheet> : null}
  </View>;
}

function contributorLabel(idea: PlannerIdea) { const first = idea.contributors[0]?.name?.split(' ')[0]; return first ? `${first}${idea.contributors.length > 1 ? ` + ${idea.contributors.length - 1}` : ''}` : ''; }
function Loading({ label }: { label: string }) { return <View style={s.loading}><ActivityIndicator color={colors.ink} /><Text style={k.body}>{label}</Text></View>; }
function sheetTitle(sheet: Sheet) {
  return ({ create: 'Make it your trip', settings: 'Trip details', transport: 'Getting around', destination: 'Find your saved places', import: 'Bring your Dreams', newIdea: 'Add an idea', idea: 'A place to go', day: 'Make this day yours', stop: 'Edit this stop', pick: sheet.kind === 'pick' && sheet.replace ? 'Swap this stop' : 'Choose a place', booking: 'Add to your day', period: 'Make time for it', stay: 'A place to stay', rework: 'Shape the days', invite: 'Invite your people', member: 'Trip access', history: 'Previous versions' })[sheet.kind];
}

function ConnectDestination({ trip, active, busy, onSubmit }: { trip: PlannerTrip; active: boolean; busy: boolean; onSubmit: (scope: PlannerDreamScope) => void }) {
  const [value, setValue] = React.useState(trip.destination), [scope, setScope] = React.useState<PlannerDreamScope | null>(trip.match_scope ?? null);
  return <><DreamDestinationField value={value} scope={scope} selectInitial active={active} disabled={busy} onChange={(text, chosen) => { setValue(text); setScope(chosen); }} />
    <Text style={[k.hint, { marginBottom: 18 }]}>These suggestions are private. You’ll choose which places to share with the trip.</Text>
    <PlannerAction label="Find my saved places" busy={busy} disabled={!scope} onPress={() => scope && onSubmit(scope)} /></>;
}

function StopRow({ stop, idea, travelLabel, editable, handle, onPress }: {
  stop: PlannerStop; idea?: PlannerIdea; travelLabel?: string; editable: boolean; onPress: () => void;
  handle?: GestureResponderHandlers & { onMoveEarlier: () => void; onMoveLater: () => void };
}) {
  const { onMoveEarlier, onMoveLater, ...panHandlers } = handle || {};
  return <View style={s.stopOuter}>
    {travelLabel ? <Text style={s.travelTime}>{travelLabel}</Text> : null}
    <View style={s.stopRow}><Text style={s.time}>{stop.start_time}</Text>
      <PressFeedback style={s.stopContent} onPress={onPress} disabled={!editable} accessibilityRole="button" accessibilityLabel={`${stop.title}, ${stop.start_time}, ${durationLabel(stop.duration_minutes)}${stop.locked ? ', locked' : ''}`}>
        {idea ? <View style={s.stopPhoto}><PlannerPhoto uri={idea.image_url} category={idea.category} title={stop.title} /></View> : null}
        <View style={{ flex: 1 }}><Text style={[s.stopTitle, stop.kind === 'break' && { fontFamily: fonts.displayItalic }]}>{stop.title}</Text>
          <Text style={k.hint}>{durationLabel(stop.duration_minutes)}{idea?.city ? ` · ${idea.city}` : ''}</Text>
          {stop.notes ? <Text style={k.hint} numberOfLines={2}>{stop.notes}</Text> : null}</View>
        {stop.locked ? <PlannerGlyph name="lock" size={15} /> : null}
      </PressFeedback>
      {handle && !stop.locked ? <View {...panHandlers} style={s.dragHandle} accessible accessibilityRole="adjustable" accessibilityLabel={`Reorder ${stop.title}`}
        accessibilityState={{ disabled: !editable }} accessibilityActions={[{ name: 'increment', label: 'Move later' }, { name: 'decrement', label: 'Move earlier' }]}
        onAccessibilityAction={event => { if (editable) { if (event.nativeEvent.actionName === 'increment') onMoveLater?.(); else if (event.nativeEvent.actionName === 'decrement') onMoveEarlier?.(); } }}><PlannerGlyph name="grip" size={17} /></View> : null}
    </View>
  </View>;
}

function ReworkForm({ trip, date, busy, onGenerate }: { trip: PlannerTrip; date?: string; busy: boolean; onGenerate: (pace: PlannerPace) => void }) {
  const [pace, setPace] = React.useState(trip.pace);
  const locks = trip.plan?.days.filter(day => !date || day.date === date).flatMap(day => day.stops.filter(stop => stop.locked)) ?? [];
  return <><Text style={[k.body, { marginBottom: 20 }]}>{date ? formatDay(date, { weekday: 'long' }) : `${trip.destination} · ${dateRange(trip.start_date, trip.end_date)}`}</Text>
    <Text style={[k.body, { marginBottom: 6 }]}>{savedIdeaSummary(trip.ideas)}</Text>
    <Text style={[k.hint, { marginBottom: 20 }]}>Saved stay options are considered for your nights separately.</Text>
    <PlannerChoices label="How should it feel?" value={pace} choices={PACES} onChange={setPace} disabled={busy} />
    {locks.length ? <View style={{ gap: 12, marginBottom: 22 }}><Text style={k.label}>Keeping these stops</Text>{locks.map(stop => <View key={stop.id} style={{ flexDirection: 'row', gap: 10, alignItems: 'center' }}><PlannerGlyph name="lock" size={14} /><Text style={k.body}>{stop.title} · {stop.start_time}</Text></View>)}</View> : null}
    <Text style={[k.body, { marginBottom: 22 }]}>{date ? 'Rework this day using your saved places.' : 'Plan every day of your trip using your saved places.'} Your own plans and fixed bookings stay in place.</Text>
    <PlannerAction label={trip.plan ? 'Preview a new plan' : 'Create draft itinerary'} prominent busy={busy} onPress={() => onGenerate(pace)} disabled={!trip.ideas.length} />
    <Text style={[k.hint, { marginTop: 12 }]}>Your current plan stays in place until you accept the draft.</Text>
  </>;
}

function IdeaDetails({ idea, editable, busy, onSource, onUpdate, onRemove, onAddToPlan }: {
  idea: PlannerIdea; editable: boolean; busy: boolean; onSource: (url: string) => void;
  onUpdate: (values: { duration_minutes: number; must_do: boolean }) => void; onRemove: () => void; onAddToPlan?: () => void;
}) {
  const [duration, setDuration] = React.useState(String(idea.duration_minutes)), [mustDo, setMustDo] = React.useState(idea.must_do), [remove, setRemove] = React.useState(false);
  return <><View style={s.detailPhoto}><PlannerPhoto uri={idea.image_url} category={idea.category} title={idea.title} large /></View>
    <Text style={[s.sectionTitle, { marginVertical: 14 }]}>{idea.title}</Text><Text style={k.body}>{[idea.city, idea.country].filter(Boolean).join(' · ')}</Text>
    <Text style={[k.hint, { marginVertical: 12 }]}>Shared by {idea.contributors.map(value => value.name).join(', ') || 'a traveller'}{idea.source_count > 1 ? ` · ${idea.source_count} posts` : ''}</Text>
    {idea.google_place_id || (Number.isFinite(idea.latitude) && Number.isFinite(idea.longitude)) ? <PlannerAction label="Open in Maps" quiet onPress={() => onSource(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(Number.isFinite(idea.latitude) && Number.isFinite(idea.longitude) ? `${idea.latitude},${idea.longitude}` : idea.title)}${idea.google_place_id ? `&query_place_id=${encodeURIComponent(idea.google_place_id)}` : ''}`)} /> : null}
    {idea.source_url ? <PlannerAction label="View original post" quiet onPress={() => onSource(idea.source_url!)} /> : null}
    {editable ? <><PlannerField label="Visit duration, in minutes" value={duration} onChangeText={setDuration} keyboardType="numeric" />
      <PressFeedback style={s.checkRow} onPress={() => setMustDo(value => !value)} accessibilityRole="checkbox" accessibilityState={{ checked: mustDo }}><Check checked={mustDo} /><Text style={k.body}>Make this a must-do</Text></PressFeedback>
      <PlannerAction label="Save details" busy={busy} disabled={!Number.isInteger(Number(duration)) || Number(duration) < 5 || Number(duration) > 720} onPress={() => onUpdate({ duration_minutes: Number(duration), must_do: mustDo })} />
      {onAddToPlan ? <PlannerAction label="Place in the plan" quiet onPress={onAddToPlan} disabled={busy} /> : null}
      <PlannerAction label={remove ? 'Confirm removal from Ideas' : 'Remove from Ideas'} quiet disabled={busy} onPress={() => remove ? onRemove() : setRemove(true)} /></> : null}
  </>;
}

function BookingImport({ trip, busy, onImport }: { trip: PlannerTrip; busy: boolean; onImport: (ids: string[]) => void }) {
  const [open, setOpen] = React.useState(false), [loading, setLoading] = React.useState(false), [error, setError] = React.useState('');
  const [bookings, setBookings] = React.useState<Awaited<ReturnType<typeof plannerApi.bookings>>['bookings']>([]), [selected, setSelected] = React.useState<string[]>([]);
  React.useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setLoading(true); setError('');
    void plannerApi.bookings(trip.id, controller.signal).then(result => { if (!controller.signal.aborted) setBookings(result.bookings); })
      .catch(cause => { if (!controller.signal.aborted) setError(errorText(cause)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, trip.id]);
  return <View style={{ marginBottom: 24 }}><PlannerAction label={open ? 'Close your flights' : 'Choose from your flights'} secondary disabled={busy} onPress={() => setOpen(value => !value)} />
    {open ? <View style={{ marginTop: 12 }}>{loading ? <ActivityIndicator color={colors.ink} /> : error ? <Text style={k.error}>{error}</Text> : !bookings.length ? <Text style={k.hint}>No flights match these trip dates.</Text> : <>
      {bookings.map(booking => <PressFeedback key={booking.segment_id} style={s.checkRow} disabled={busy} accessibilityRole="checkbox" accessibilityState={{ checked: selected.includes(booking.segment_id) }} onPress={() => setSelected(current => current.includes(booking.segment_id) ? current.filter(value => value !== booking.segment_id) : [...current, booking.segment_id])}>
        <Check checked={selected.includes(booking.segment_id)} /><View style={{ flex: 1 }}><Text style={s.memberName}>{booking.title}</Text><Text style={k.hint}>{formatDay(booking.date)} · {booking.start_time} · {durationLabel(booking.duration_minutes)}</Text></View></PressFeedback>)}
      <Text style={[k.hint, { marginVertical: 12 }]}>Only these flight details are shared. Booking references and emails stay private.</Text><PlannerAction label="Add selected flights" disabled={!selected.length} busy={busy} onPress={() => onImport(selected)} />
    </>}</View> : null}</View>;
}

function BookingForm({ busy, onSubmit }: { busy: boolean; onSubmit: (stop: PlannerStop) => void }) {
  const [kind, setKind] = React.useState<'booking' | 'break'>('booking'), [title, setTitle] = React.useState(''), [time, setTime] = React.useState('12:00'), [duration, setDuration] = React.useState('60'), [note, setNote] = React.useState('');
  return <><PlannerChoices value={kind} choices={[{ value: 'booking', label: 'Fixed booking' }, { value: 'break', label: 'Free time' }]} onChange={setKind} />
    <PlannerField label="Name" value={title} onChangeText={setTitle} placeholder={kind === 'booking' ? 'Dinner reservation' : 'An open afternoon'} />
    <View style={{ flexDirection: 'row', gap: 12 }}><View style={{ flex: 1 }}><PlannerField label="Start time" value={time} onChangeText={setTime} keyboardType="numbers-and-punctuation" /></View><View style={{ flex: 1 }}><PlannerField label="Minutes" value={duration} onChangeText={setDuration} keyboardType="numeric" /></View></View>
    <PlannerField label="Note (optional)" value={note} onChangeText={setNote} multiline />
    <PlannerAction label="Add to this day" busy={busy} disabled={!title.trim() || !Number.isFinite(minutes(time)) || !Number.isInteger(Number(duration)) || Number(duration) < 5 || Number(duration) > (kind === 'booking' ? 2880 : 1440)}
      onPress={() => onSubmit({ id: id(), title: title.trim(), start_time: time, duration_minutes: Number(duration), locked: kind === 'booking', kind, notes: note.trim(), ...(kind === 'break' ? { user_created: true } : {}) })} /></>;
}

function InviteForm({ trip, busy, run }: { trip: PlannerTrip; busy: boolean; run: (label: string, work: () => Promise<void>) => Promise<void> }) {
  const [role, setRole] = React.useState<'contributor' | 'editor'>('contributor'), [email, setEmail] = React.useState(''), [targeted, setTargeted] = React.useState(false);
  const [created, setCreated] = React.useState<{ key: string; url: string }>(), [notice, setNotice] = React.useState('');
  const request = React.useRef<{ key: string; id: string } | undefined>(undefined);
  const key = JSON.stringify([role, targeted ? email.trim().toLowerCase() : '']);
  const getLink = async () => {
    if (created?.key === key) return created.url;
    if (targeted && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) throw new Error('Enter the email address your friend uses for Trotter.');
    if (request.current?.key !== key) request.current = { key, id: id() };
    const result = await plannerApi.invite(trip.id, { role, ...(targeted ? { recipient_email: email.trim().toLowerCase(), label: email.trim() } : {}), client_request_id: request.current.id });
    setCreated({ key, url: result.share_url }); return result.share_url;
  };
  const send = (copy: boolean) => void run(copy ? 'Preparing link…' : 'Preparing invitation…', async () => {
    const url = await getLink();
    if (copy) {
      const navigator = (globalThis as any).navigator;
      if (Platform.OS === 'web') { if (navigator?.clipboard?.writeText) await navigator.clipboard.writeText(url); else { setNotice('Select and copy the link below.'); return; } }
      else Clipboard.setString(url);
      setNotice('Invitation link copied.'); return;
    }
    try { await Share.share({ title: trip.title, message: `Come along on ${trip.title}. Join our trip in Trotter: ${url}`, ...(Platform.OS === 'ios' ? { url } : {}) }); }
    catch (cause) { if (!(cause instanceof Error && cause.name === 'AbortError')) throw cause; }
  });
  return <><View style={s.inviteFormCover}><PlannerPhoto uri={trip.cover_image_url} country={trip.destination} cover title={trip.destination} /></View>
    <Text style={[s.sectionTitle, { marginTop: 18 }]}>{trip.title}</Text><Text style={[k.body, { marginTop: 4, marginBottom: 22 }]}>{dateRange(trip.start_date, trip.end_date)}</Text>
    <PlannerChoices label="They can" value={role} choices={[{ value: 'contributor', label: 'Add ideas & vote' }, { value: 'editor', label: 'Edit the plan' }]} onChange={setRole} disabled={busy} />
    <PressFeedback style={s.checkRow} onPress={() => setTargeted(value => !value)} accessibilityRole="checkbox" accessibilityState={{ checked: targeted }}><Check checked={targeted} /><Text style={k.body}>Limit this invitation to one person</Text></PressFeedback>
    {targeted ? <PlannerField label="Their Trotter email" value={email} onChangeText={setEmail} keyboardType="email-address" placeholder="friend@example.com" hint="Only this account can accept. You share the invitation link yourself." /> : null}
    {notice ? <Text style={[k.hint, { marginBottom: 12 }]} accessibilityLiveRegion="polite">{notice}</Text> : null}
    <PlannerAction label="Share invitation" onPress={() => send(false)} disabled={busy} /><PlannerAction label="Copy link" quiet onPress={() => send(true)} disabled={busy} />
    {created?.key === key ? <Text selectable style={[k.hint, { marginTop: 8 }]}>{created.url}</Text> : null}
    <Text style={[k.hint, { marginTop: 12 }]}>You can change access or revoke the invitation in People.</Text>
  </>;
}

function MemberForm({ member, busy, onRole, onRemove }: { member: PlannerMember; busy: boolean; onRole: (role: 'editor' | 'contributor') => void; onRemove: () => void }) {
  const [role, setRole] = React.useState<'editor' | 'contributor'>(member.role === 'editor' ? 'editor' : 'contributor'), [confirm, setConfirm] = React.useState(false);
  return <><Text style={[s.sectionTitle, { marginBottom: 18 }]}>{member.name}</Text><PlannerChoices label="They can" value={role} choices={[{ value: 'contributor', label: 'Add ideas & vote' }, { value: 'editor', label: 'Edit the plan' }]} onChange={setRole} />
    <PlannerAction label="Save access" busy={busy} onPress={() => onRole(role)} /><PlannerAction label={confirm ? 'Confirm removal' : 'Remove from trip'} quiet disabled={busy} onPress={() => confirm ? onRemove() : setConfirm(true)} />
    {confirm ? <Text style={k.hint}>They will lose access to this trip. Places already shared remain in the group.</Text> : null}</>;
}
function LeaveTrip({ busy, onLeave }: { busy: boolean; onLeave: () => void }) {
  const [confirm, setConfirm] = React.useState(false);
  return <View style={{ marginTop: 30 }}><PlannerAction label={confirm ? 'Confirm leaving this trip' : 'Leave trip'} quiet disabled={busy} onPress={() => confirm ? onLeave() : setConfirm(true)} />{confirm ? <Text style={k.hint}>Your shared ideas remain with the group.</Text> : null}</View>;
}
function DeleteTrip({ busy, onDelete }: { busy: boolean; onDelete: () => void }) {
  const [confirm, setConfirm] = React.useState(false);
  return <View style={{ marginTop: 26 }}>{confirm ? <Text style={k.hint}>Delete this trip for everyone? Your personal Dreams and flights will stay in Trotter.</Text> : null}<PlannerAction label={confirm ? 'Delete this trip for everyone' : 'Delete trip'} quiet disabled={busy} onPress={() => confirm ? onDelete() : setConfirm(true)} />{confirm ? <PlannerAction label="Keep trip" quiet disabled={busy} onPress={() => setConfirm(false)} /> : null}</View>;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paperSoft },
  header: { ...headerRowStyle, justifyContent: 'space-between' },
  back: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 9 },
  backText: { fontFamily: fonts.sansRegular, fontSize: 15, color: colors.ink },
  brand: { fontFamily: fonts.displayItalic, fontSize: 29, color: colors.ink, alignSelf: 'center' },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#DCE3DF', alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontFamily: fonts.sans, fontSize: 18, color: colors.ink },
  content: { paddingHorizontal: 24, maxWidth: 680, width: '100%', alignSelf: 'center' },
  title: { fontFamily: fonts.displayItalic, fontSize: 34, lineHeight: 39, color: colors.ink, marginBottom: 6 },
  sectionTitle: { fontFamily: fonts.display, fontSize: 27, lineHeight: 32, color: colors.ink },
  homeHeading: { paddingTop: 15, paddingBottom: 24 },
  tripList: { gap: 28, paddingTop: 30 },
  tripCard: { borderWidth: 1, borderColor: colors.paperBorderSoft, backgroundColor: colors.paperPhoto, padding: 6 },
  cardCover: { height: 172, overflow: 'hidden' },
  cardCaption: { paddingHorizontal: 10, paddingTop: 14, paddingBottom: 12 },
  cardTitle: { fontFamily: fonts.display, fontSize: 29, color: colors.ink, marginBottom: 6 },
  empty: { paddingVertical: 38, gap: 18 },
  loading: { alignItems: 'center', justifyContent: 'center', gap: 14, paddingVertical: 55 },
  loadingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 10 },
  feedback: { paddingVertical: 12, gap: 10 },
  notice: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.ink, paddingVertical: 12 },
  tripHeading: { flexDirection: 'row', alignItems: 'flex-start', paddingTop: 8, paddingBottom: 12, gap: 6 },
  tabs: { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: colors.paperBorder, marginBottom: 10 },
  tab: { flex: 1, minHeight: 48, justifyContent: 'center', alignItems: 'center', borderBottomWidth: 2, borderBottomColor: 'transparent' },
  selectedTab: { borderBottomColor: colors.ink },
  tabText: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 15 },
  selectedTabText: { fontFamily: fonts.sansSemi, color: colors.ink },
  sectionRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, minHeight: 48 },
  ideaRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  ideaContent: { flex: 1, minHeight: 102, flexDirection: 'row', alignItems: 'center', gap: 14 },
  ideaPhoto: { width: 78, height: 84, borderRadius: 3, overflow: 'hidden' },
  ideaCopy: { flex: 1, gap: 6, paddingRight: 3 },
  placeTitle: { fontFamily: fonts.display, color: colors.ink, fontSize: 23, lineHeight: 27 },
  metadata: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, lineHeight: 18 },
  statusText: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 11, lineHeight: 16 },
  voteColumn: { width: 44, alignItems: 'center' },
  voteTarget: { width: 44, height: 44, justifyContent: 'center', alignItems: 'center' },
  score: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, lineHeight: 14, textAlign: 'center' },
  member: { flexDirection: 'row', alignItems: 'center', gap: 14, minHeight: 84, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  memberAvatar: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  memberInitial: { fontFamily: fonts.sansRegular, fontSize: 20, color: colors.ink },
  memberName: { fontFamily: fonts.display, color: colors.ink, fontSize: 22, lineHeight: 27 },
  inviteRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  invitation: { gap: 12, paddingTop: 10 },
  inviteCover: { height: 260, marginBottom: 14, borderWidth: 5, borderColor: colors.paperPhoto, overflow: 'hidden' },
  invitationCopy: { fontFamily: fonts.displayItalic, color: colors.ink, fontSize: 26, lineHeight: 31, textAlign: 'center', paddingVertical: 22 },
  inviteFormCover: { height: 190, borderWidth: 4, borderColor: colors.paperPhoto },
  job: { paddingVertical: 17, flexDirection: 'row', alignItems: 'center', gap: 12 },
  draftNotice: { paddingBottom: 16, borderBottomWidth: 1, borderBottomColor: colors.paperBorderSoft },
  draftLabel: { fontFamily: fonts.sans, color: colors.copper, fontSize: 13 },
  day: { paddingTop: 20, paddingBottom: 12 },
  dayHeading: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 10 },
  dayTitle: { fontFamily: fonts.displayMedium, color: colors.ink, fontSize: 28 },
  dayDate: { fontFamily: fonts.displayItalic, fontSize: 25 },
  openDay: { fontFamily: fonts.displayItalic, fontSize: 23, color: colors.mutedInk, paddingVertical: 20 },
  stopOuter: { backgroundColor: colors.paperSoft },
  stopRow: { minHeight: 94, flexDirection: 'row', alignItems: 'center', gap: 8 },
  stopContent: { flex: 1, minHeight: 82, flexDirection: 'row', alignItems: 'center', gap: 10 },
  stopPhoto: { width: 54, height: 58, overflow: 'hidden', borderRadius: 3 },
  stopTitle: { fontFamily: fonts.display, color: colors.ink, fontSize: 21, lineHeight: 25 },
  time: { fontFamily: fonts.sansRegular, color: colors.ink, fontSize: 11, width: 36 },
  travelTime: { fontFamily: fonts.sansRegular, fontSize: 11, color: colors.mutedInk, paddingLeft: 44, paddingTop: 4 },
  dragHandle: { width: 40, height: 60, alignItems: 'center', justifyContent: 'center' },
  planNotes: { gap: 8, borderTopWidth: 1, borderTopColor: colors.paperBorderSoft, paddingTop: 20, marginTop: 10 },
  planActions: { gap: 8, marginTop: 24 },
  pinnedDayNav: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: 24, backgroundColor: colors.paperSoft, zIndex: 5 },
  draftActionDock: { position: 'absolute', left: 0, right: 0, backgroundColor: colors.paperSoft, borderTopWidth: 1, borderTopColor: colors.paperBorderSoft, paddingVertical: 10, paddingHorizontal: 24 },
  draftActionInner: { width: '100%', maxWidth: 632, alignSelf: 'center' },
  detailPhoto: { height: 190, borderRadius: 3, overflow: 'hidden' },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 48, marginBottom: 16 },
  historyRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 16, borderBottomWidth: 1, borderColor: colors.paperBorderSoft },
});
