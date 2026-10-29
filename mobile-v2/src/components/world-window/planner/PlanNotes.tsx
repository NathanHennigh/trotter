import React from 'react';
import { Text, View } from 'react-native';
import { colors } from '../../../theme/trotterTheme';
import { k, PlannerAction } from './PlannerKit';

export function PlanNotes({ warnings }: { warnings: string[] }) {
  const [expanded, setExpanded] = React.useState(false);
  const unique = [...new Set(warnings)].filter(value => !/^\d+ ideas? remain(?:s)? in Ideas;/.test(value) && !value.startsWith('Stay options remain in Ideas.'));
  if (!unique.length) return null;
  return <View style={{ gap: 8, borderTopWidth: 1, borderTopColor: colors.paperBorderSoft, paddingTop: 16, marginTop: 10 }}>
    <Text style={k.label}>A few things to check</Text>
    {(expanded ? unique : unique.slice(0, 2)).map(warning => <Text key={warning} style={k.hint}>{warning}</Text>)}
    {unique.length > 2 ? <PlannerAction label={expanded ? 'Show less' : `Show ${unique.length - 2} more ${unique.length === 3 ? 'note' : 'notes'}`} quiet onPress={() => setExpanded(value => !value)} /> : null}
  </View>;
}
