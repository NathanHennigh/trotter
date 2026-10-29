import React from 'react';
import { ActivityIndicator, Image, StyleSheet, Text, View } from 'react-native';
import { plannerApi, type PlannerInvitePreview } from '../../../services/planner';
import { colors, fonts } from '../../../theme/trotterTheme';
import { findCountryArtwork } from '../dreams/countryArtwork';
import { PressFeedback } from '../motion';

export function PlannerAuthPreview({ token, onDismiss }: { token: string; onDismiss?: () => void }) {
  const [preview, setPreview] = React.useState<PlannerInvitePreview>();
  const [error, setError] = React.useState<string>();
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController();
    setPreview(undefined); setError(undefined);
    void plannerApi.previewInvite(token, controller.signal).then(value => {
      if (!controller.signal.aborted) setPreview(value);
    }).catch(caught => { if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'The invitation could not load.'); });
    return () => controller.abort();
  }, [token, attempt]);
  const artwork = findCountryArtwork(preview?.trip.destination);
  const formatDate = (value: string) => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  return <View style={s.root} accessibilityLiveRegion="polite">
    {artwork && <Image source={artwork.source} style={s.photo} accessibilityIgnoresInvertColors />}
    {!preview && !error ? <ActivityIndicator color={colors.blue} /> : null}
    <Text style={s.inviter}>{preview ? `${preview.inviter_name} invited you` : 'YOUR TRIP INVITATION'}</Text>
    <Text style={s.title} accessibilityRole="header">{preview?.trip.title || (error ? 'Let’s find your invitation' : 'A trip is waiting for you')}</Text>
    {preview ? <Text style={s.dates}>{formatDate(preview.trip.start_date)} – {formatDate(preview.trip.end_date)}</Text> : null}
    <Text style={s.body}>{error || 'Sign in to review the trip and join your people. Your personal Dreams stay private.'}</Text>
    {error ? <PressFeedback accessibilityRole="button" onPress={() => setAttempt(value => value + 1)} style={s.link}><Text style={s.linkText}>Try again</Text></PressFeedback> : null}
    {onDismiss ? <PressFeedback accessibilityRole="button" onPress={onDismiss} style={s.link}><Text style={s.linkText}>Maybe later</Text></PressFeedback> : null}
  </View>;
}

const s = StyleSheet.create({
  root: { width: '100%', gap: 12, paddingVertical: 14 },
  photo: { height: 170, width: '100%', borderRadius: 3, marginBottom: 8 },
  inviter: { fontFamily: fonts.sansRegular, fontSize: 13, color: colors.mutedInk },
  title: { fontFamily: fonts.display, fontSize: 34, lineHeight: 39, color: colors.ink },
  dates: { fontFamily: fonts.sansRegular, fontSize: 14, color: colors.mutedInk },
  body: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 21, color: colors.mutedInk },
  link: { minHeight: 44, alignSelf: 'flex-start', justifyContent: 'center' },
  linkText: { color: colors.blue, fontFamily: fonts.sans, fontSize: 14 },
});
