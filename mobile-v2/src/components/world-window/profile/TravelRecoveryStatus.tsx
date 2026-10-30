import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useTravelIdentity } from '../../../services/travelIdentity';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { recoveryMessage } from './travelNamePresentation';

export function TravelRecoveryStatus() {
  const { identity, saving, retryRecovery } = useTravelIdentity();
  const [error, setError] = React.useState('');
  const job = identity?.recovery;
  if (!job) return null;
  const copy = recoveryMessage(job), pending = job.state === 'queued' || job.state === 'running';
  return <View style={s.status} accessibilityLiveRegion="polite">
    <View style={s.heading}>{pending ? <ActivityIndicator size="small" color={colors.blue} /> : null}<Text style={s.title}>{copy.title}</Text></View>
    <Text style={s.detail}>{copy.detail}</Text>
    {job.state === 'failed' ? <PressFeedback accessibilityRole="button" accessibilityState={{ disabled: saving, busy: saving }} disabled={saving} style={s.retry}
      onPress={() => { setError(''); void retryRecovery().catch(cause => setError(cause instanceof Error ? cause.message : 'Please try again.')); }}><Text style={s.link}>{saving ? 'Retrying…' : 'Retry booking check'}</Text></PressFeedback> : null}
    {error ? <Text style={s.error} accessibilityRole="alert">{error}</Text> : null}
  </View>;
}
const s = StyleSheet.create({
  status: { paddingVertical: 17, borderTopWidth: 1, borderTopColor: colors.paperBorder, gap: 6 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: 9 }, title: { flex: 1, fontFamily: fonts.sans, fontSize: 14, lineHeight: 21, color: colors.ink },
  detail: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.mutedInk }, retry: { minHeight: 48, justifyContent: 'center', alignSelf: 'flex-start' }, link: { fontFamily: fonts.sans, fontSize: 13, color: colors.blue }, error: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 19, color: colors.redDeep },
});
