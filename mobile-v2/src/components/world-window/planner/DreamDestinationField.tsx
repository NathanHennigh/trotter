import React from 'react';
import { Text, View } from 'react-native';
import { plannerApi, type PlannerDreamDestination, type PlannerDreamScope } from '../../../services/planner';
import { getAuthRevision } from '../../../services/travelTrips';
import { PressFeedback } from '../motion';
import { k, PlannerAction, PlannerField } from './PlannerKit';

/** Destination choices come from categorized saves, never a free-text geography guess. */
export function DreamDestinationField({ value, scope, onChange, disabled, active = true, selectInitial = false }: {
  value: string; scope: PlannerDreamScope | null; onChange: (value: string, scope: PlannerDreamScope | null) => void;
  disabled?: boolean; active?: boolean; selectInitial?: boolean;
}) {
  const [choices, setChoices] = React.useState<PlannerDreamDestination[]>([]), [open, setOpen] = React.useState(false);
  const [error, setError] = React.useState(false), [retry, setRetry] = React.useState(0);
  const current = React.useRef({ value, scope, onChange }); current.current = { value, scope, onChange };
  const initial = React.useRef(selectInitial ? value : undefined);
  React.useEffect(() => {
    if (!active) return;
    const controller = new AbortController(), revision = getAuthRevision();
    void plannerApi.dreamDestinations(controller.signal).then(result => {
      if (controller.signal.aborted || revision !== getAuthRevision()) return;
      setChoices(result.destinations); setError(false);
      if (initial.current && initial.current === current.current.value && !current.current.scope) {
        const exact = result.destinations.find(option => option.label.toLocaleLowerCase() === initial.current!.trim().toLocaleLowerCase());
        if (exact) current.current.onChange(exact.label, exact);
      }
      initial.current = undefined;
    }).catch(() => { if (!controller.signal.aborted && revision === getAuthRevision()) setError(true); });
    return () => controller.abort();
  }, [active, retry]);
  const matches = choices.filter(option => !value || option.label.toLocaleLowerCase().includes(value.trim().toLocaleLowerCase())).slice(0, 7);
  return <View>
    <PlannerField label="Destination" value={value} editable={!disabled} placeholder="Country or city"
      onFocus={() => setOpen(true)} onChangeText={text => { initial.current = undefined; setOpen(true); onChange(text, null); }} />
    {open && matches.length ? <View style={{ marginTop: -10, marginBottom: 14 }}>
      {matches.map(option => <PressFeedback key={option.id} accessibilityRole="button" accessibilityLabel={`Choose ${option.label}`} disabled={disabled}
        style={{ minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}
        onPress={() => { onChange(option.label, option); setOpen(false); }}>
        <Text style={k.body}>{option.label}</Text><Text style={k.hint}>{option.count} in Dreams</Text>
      </PressFeedback>)}
    </View> : null}
    {scope ? <Text style={[k.hint, { marginTop: -10, marginBottom: 16 }]}>Find your saved places in {scope.label}. You choose what to share.</Text>
      : error ? <PlannerAction label="Retry destinations from Dreams" quiet onPress={() => setRetry(value => value + 1)} disabled={disabled} /> : null}
  </View>;
}
