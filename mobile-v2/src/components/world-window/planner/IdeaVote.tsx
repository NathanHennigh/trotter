import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { plannerApi, type PlannerIdea, type PlannerTrip } from '../../../services/planner';
import { getAuthRevision } from '../../../services/travelTrips';
import { colors, fonts } from '../../../theme/trotterTheme';
import { selectionHaptic } from '../../../utils/experiencePreferences';
import { PressFeedback } from '../motion';
import { PlannerGlyph } from './PlannerKit';
import { nextVote } from './plannerEditing';

/** Vote feedback stays in the margin so a request never shifts the list. */
export function IdeaVote({ tripId, idea, disabled, onUpdate, onError }: {
  tripId: string; idea: PlannerIdea; disabled?: boolean; onUpdate: (trip: PlannerTrip, ideaId: string) => void; onError: (message: string) => void;
}) {
  const [pending, setPending] = React.useState<{ vote: -1 | 0 | 1; score: number }>();
  const inFlight = React.useRef(false), mounted = React.useRef(true);
  React.useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const vote = pending?.vote ?? idea.my_vote, score = pending?.score ?? idea.score;
  const choose = async (pressed: -1 | 1) => {
    if (disabled || inFlight.current) return;
    inFlight.current = true;
    const revision = getAuthRevision(), value = nextVote(idea.my_vote, pressed);
    setPending({ vote: value, score: idea.score - idea.my_vote + value }); selectionHaptic();
    try {
      const result = await plannerApi.vote(tripId, idea.id, value);
      if (mounted.current && revision === getAuthRevision()) onUpdate(result, idea.id);
    } catch (cause) {
      if (mounted.current && revision === getAuthRevision()) onError(cause instanceof Error ? cause.message : 'Your vote could not be saved. Try again.');
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(undefined);
    }
  };
  return <View style={s.column}>
    <PressFeedback style={s.target} accessibilityRole="button" accessibilityLabel={`Vote for ${idea.title}`} accessibilityState={{ selected: vote === 1, disabled: disabled || !!pending, busy: !!pending }} disabled={disabled || !!pending} onPress={() => void choose(1)}>
      <PlannerGlyph name="up" size={14} color={vote === 1 ? colors.copper : colors.mutedInk} />
    </PressFeedback>
    <Text style={s.score} accessibilityLabel={`Group score ${score}`} accessibilityLiveRegion="polite">{score}</Text>
    <PressFeedback style={s.target} accessibilityRole="button" accessibilityLabel={`Vote against ${idea.title}`} accessibilityState={{ selected: vote === -1, disabled: disabled || !!pending, busy: !!pending }} disabled={disabled || !!pending} onPress={() => void choose(-1)}>
      <PlannerGlyph name="down" size={14} color={vote === -1 ? colors.copper : colors.mutedInk} />
    </PressFeedback>
  </View>;
}
const s = StyleSheet.create({
  column: { width: 44, alignItems: 'center' },
  target: { width: 44, height: 44, justifyContent: 'center', alignItems: 'center' },
  score: { fontFamily: fonts.sansRegular, color: colors.mutedInk, fontSize: 12, lineHeight: 14, textAlign: 'center' },
});
