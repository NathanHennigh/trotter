import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import type { PlannerIdea, PlannerPlan, PlannerStay, PlannerStop } from '../../../services/planner';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { WWIcon } from '../WorldWindowUI';
import { IdeaPicker } from './PlannerForms';
import { k, PlannerAction, PlannerChoices, PlannerField, PlannerPhoto } from './PlannerKit';
import { isStayIdea, type PlannerPeriodGap } from './plannerEditing';

export function PeriodGapRow({ gap, onPress }: { gap: PlannerPeriodGap; onPress?: () => void }) {
  const content = <><Text style={s.time}>{gap.start_time}</Text><View style={{ flex: 1 }}><Text style={s.free}>{gap.label === 'Lunch' ? 'Lunch to plan' : `Free ${gap.label.toLowerCase()}`}</Text><Text style={s.until}>Until {gap.end_time}</Text></View>{onPress ? <WWIcon name="plus" size={14} color={colors.mutedInk} /> : null}</>;
  return onPress ? <PressFeedback style={s.gap} accessibilityRole="button" accessibilityLabel={`Add a plan for ${gap.label.toLowerCase()}, ${gap.start_time} to ${gap.end_time}`} onPress={onPress}>{content}</PressFeedback> : <View style={s.gap}>{content}</View>;
}

export function PeriodPlanForm({ gap, ideas, plan, busy, onPlace, onText }: {
  gap: PlannerPeriodGap; ideas: PlannerIdea[]; plan: PlannerPlan | null; busy: boolean;
  onPlace: (idea: PlannerIdea) => void; onText: (value: Pick<PlannerStop, 'title' | 'start_time' | 'duration_minutes' | 'kind' | 'locked' | 'user_created'>) => void;
}) {
  const [mode, setMode] = React.useState<'place' | 'text'>('place'), [title, setTitle] = React.useState(''), [duration, setDuration] = React.useState(String(gap.duration_minutes));
  const [error, setError] = React.useState('');
  const submit = () => {
    if (!title.trim()) { setError('Give this part of your day a name.'); return; }
    if (!Number.isInteger(Number(duration)) || Number(duration) < 5 || Number(duration) > gap.duration_minutes) { setError(`Choose between 5 and ${gap.duration_minutes} minutes for this opening.`); return; }
    onText({ title: title.trim(), start_time: gap.start_time, duration_minutes: Number(duration), kind: 'break', locked: false, user_created: true });
  };
  return <><Text style={[k.body, { marginBottom: 18 }]}>{gap.label} · {gap.start_time}–{gap.end_time}</Text>
    <PlannerChoices value={mode} choices={[{ value: 'place', label: 'A saved place' }, { value: 'text', label: 'My own plan' }]} onChange={setMode} disabled={busy} />
    {mode === 'place' ? <IdeaPicker ideas={ideas} plan={plan} busy={busy} onChoose={onPlace} /> : <>
      <PlannerField label="What would you like to do?" value={title} onChangeText={setTitle} placeholder={gap.label === 'Morning' ? 'Slow morning' : gap.label === 'Lunch' ? 'Lunch with friends' : gap.label === 'Afternoon' ? 'A free afternoon' : 'Dinner with friends'} editable={!busy} />
      <PlannerField label="Minutes" value={duration} onChangeText={setDuration} keyboardType="numeric" editable={!busy} />
      <Text style={[k.hint, { marginBottom: 18 }]}>Reworking your itinerary will keep this plan. You can edit or move it anytime.</Text>
      {error ? <Text style={k.error} accessibilityRole="alert">{error}</Text> : null}<PlannerAction label="Add to this day" prominent busy={busy} onPress={submit} />
    </>}
  </>;
}

export function StayRow({ stay, ideas, onPress }: { stay?: PlannerStay; ideas: PlannerIdea[]; onPress?: () => void }) {
  const idea = stay?.idea_id && ['suggested', 'selected'].includes(stay.status) ? ideas.find(item => item.id === stay.idea_id && isStayIdea(item)) : undefined;
  const title = stay?.status === 'not_needed' ? 'No accommodation needed' : idea ? idea.title : 'Accommodation needed';
  const content = <>{idea ? <View style={s.photo}><PlannerPhoto uri={idea.image_url} category={idea.category} title={idea.title} /></View> : <View style={s.night}><Text style={s.nightMark}>☾</Text></View>}
    <View style={{ flex: 1 }}>{idea ? <Text style={k.hint}>{stay?.status === 'selected' ? 'Selected stay' : 'Suggested stay'}</Text> : null}<Text style={s.stayTitle}>{title}</Text>
      {stay?.reason ? <Text style={k.hint}>{stay.reason}</Text> : idea ? <Text style={k.hint}>{idea.city || stay?.city || 'Saved in Ideas'}</Text> : stay?.status !== 'not_needed' ? <Text style={k.hint}>{stay?.city ? `For the night in ${stay.city}` : 'Choose from the stays saved in Ideas'}</Text> : null}</View>
    {onPress ? <WWIcon name="chevron" size={14} color={colors.mutedInk} /> : null}</>;
  return onPress ? <PressFeedback style={s.stay} accessibilityRole="button" accessibilityLabel={`Choose accommodation, ${title}`} onPress={onPress}>{content}</PressFeedback> : <View style={s.stay}>{content}</View>;
}

export function StayPicker({ ideas, stay, busy, onChoose }: { ideas: PlannerIdea[]; stay?: PlannerStay; busy: boolean; onChoose: (stay: PlannerStay) => void }) {
  const hotels = ideas.filter(isStayIdea);
  return <><Text style={[k.body, { marginBottom: 18 }]}>Choose from this trip’s saved stays. Choosing one doesn’t book it.</Text>
    {stay?.reason ? <Text style={[k.hint, { marginBottom: 18 }]}>{stay.reason}</Text> : null}
    {hotels.length ? hotels.map(idea => <PressFeedback key={idea.id} style={s.stayChoice} disabled={busy} accessibilityRole="button" accessibilityLabel={`Choose ${idea.title} for this night`}
      onPress={() => onChoose({ status: 'selected', idea_id: idea.id, ...(idea.city ? { city: idea.city } : {}) })}>
      <View style={s.photo}><PlannerPhoto uri={idea.image_url} category={idea.category} title={idea.title} /></View><View style={{ flex: 1 }}><Text style={s.stayTitle}>{idea.title}</Text><Text style={k.hint}>{idea.city || idea.country}</Text></View>
      {stay?.idea_id === idea.id ? <WWIcon name="check" size={18} /> : <WWIcon name="plus" size={16} />}
    </PressFeedback>) : <Text style={[k.hint, { marginBottom: 18 }]}>There aren’t any saved stays in this trip yet. Add one to Ideas when you find somewhere you like.</Text>}
    <PlannerAction label="Leave accommodation to decide" quiet disabled={busy} onPress={() => onChoose({ status: 'needed', ...(stay?.city ? { city: stay.city } : {}) })} />
    <PlannerAction label="No accommodation needed this night" quiet disabled={busy} onPress={() => onChoose({ status: 'not_needed' })} />
  </>;
}

const s = StyleSheet.create({
  gap: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 48, paddingVertical: 6, paddingRight: 12 },
  time: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 11, width: 36 },
  free: { fontFamily: fonts.displayItalic, color: colors.mutedInk, fontSize: 17, lineHeight: 21 },
  until: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 11, lineHeight: 15 },
  stay: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14, minHeight: 72, borderTopWidth: 1, borderColor: colors.paperBorderSoft, marginTop: 10 },
  stayChoice: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, minHeight: 72 },
  photo: { width: 48, height: 52, borderRadius: 3, overflow: 'hidden' },
  night: { width: 36, alignItems: 'center' },
  nightMark: { color: colors.mutedInk, fontSize: 23 },
  stayTitle: { fontFamily: fonts.sans, color: colors.ink, fontSize: 15, lineHeight: 21 },
});
