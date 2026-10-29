import React from 'react';
import { Text, View } from 'react-native';
import type { PlannerIdea, PlannerPlan, PlannerTransport } from '../../../services/planner';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { k, PlannerAction } from './PlannerKit';
import { TransportChoices } from './PlannerForms';
import { currentExclusionReason, exclusionText, transportReasonApplies, unscheduledActivities } from './plannerResultModel';

export function UnscheduledActivities({ plan, ideas, modes, onIdea, onTransport }: {
  plan: PlannerPlan; ideas: PlannerIdea[]; modes: readonly PlannerTransport[];
  onIdea: (idea: PlannerIdea) => void; onTransport?: () => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const remaining = unscheduledActivities(plan, ideas);
  if (!remaining.length) return null;
  const transport = remaining.some(idea => transportReasonApplies(plan.unplaced_reasons?.[idea.id], modes));
  return <View style={{ borderTopWidth: 1, borderTopColor: colors.paperBorderSoft, paddingTop: 18, marginTop: 12, gap: 12 }}>
    <Text style={k.label}>Not in this version · {remaining.length} {remaining.length === 1 ? 'activity' : 'activities'}</Text>
    {(expanded ? remaining : remaining.slice(0, 2)).map(idea => <PressFeedback key={idea.id} onPress={() => onIdea(idea)}
      accessibilityRole="button" accessibilityLabel={`Review ${idea.title}`} style={{ minHeight: 48, paddingVertical: 4, gap: 4 }}>
      <Text style={{ color: colors.ink, fontFamily: fonts.sans, fontSize: 15 }}>{idea.title}</Text>
      <Text style={k.hint}>{exclusionText(currentExclusionReason(idea, plan.unplaced_reasons?.[idea.id]), modes)}</Text>
    </PressFeedback>)}
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
      {remaining.length > 2 ? <PlannerAction quiet label={expanded ? 'Show less' : `Show ${remaining.length - 2} more`} onPress={() => setExpanded(value => !value)} /> : null}
      {transport && onTransport ? <PlannerAction quiet label="Getting around" onPress={onTransport} /> : null}
    </View>
  </View>;
}

export function PlannerTransportForm({ modes, busy, onSave }: { modes: PlannerTransport[]; busy: boolean; onSave: (modes: PlannerTransport[]) => void }) {
  const [selected, setSelected] = React.useState(modes);
  return <>
    <TransportChoices values={selected} onChange={setSelected} disabled={busy} />
    <Text style={[k.hint, { marginBottom: 20 }]}>Save your travel options, then rework the plan when you’re ready.</Text>
    <PlannerAction label="Save travel options" disabled={!selected.length} busy={busy} onPress={() => onSave(selected)} />
  </>;
}
