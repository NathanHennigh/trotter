import React from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, View } from 'react-native';
import { getApiBaseUrl, getAuthRevision, getStoredToken, useTravelTrips } from '../../../services/travelTrips';
import { AppleSignInCanceled } from '../../../services/appleAuth';
import { GoogleSignInCanceled } from '../../../services/googleAuth';
import { deleteVerifiedAccount, getDeletionPreview, linkAppleAccount, type AccountProvider, type AccountScope, type DeletionPreview } from '../../../services/accountLifecycle';
import { colors, fonts } from '../../../theme/trotterTheme';
import { PressFeedback } from '../motion';
import { PlannerSheet } from '../planner/PlannerKit';
import { AppleSignInButton } from './AppleSignInButton';
import { isAppleSignInEnabled } from '../../../services/appleSignInAvailability';

export function AccountControls() {
  const { accountId, accountEmail, authProviders, demoSession, signOut, finishAccountDeletion, refresh } = useTravelTrips();
  const [operation, setOperation] = React.useState<'link' | 'preview' | 'delete'>();
  const [error, setError] = React.useState<string>();
  const [deleting, setDeleting] = React.useState(false);
  const [confirmed, setConfirmed] = React.useState(false);
  const [preview, setPreview] = React.useState<DeletionPreview>();
  const live = React.useRef(true), attempt = React.useRef(0), pending = React.useRef(false);
  React.useEffect(() => { live.current = true; return () => { live.current = false; attempt.current += 1; }; }, []);
  const scope = (): AccountScope => {
    const token = getStoredToken(), revision = getAuthRevision(), currentAttempt = ++attempt.current;
    if (!token || !accountId) throw new Error('Sign in again to manage your account.');
    return { base: getApiBaseUrl(), token, ownerId: accountId,
      isCurrent: () => live.current && attempt.current === currentAttempt && getAuthRevision() === revision && getStoredToken() === token };
  };
  const run = async (kind: 'link' | 'preview' | 'delete', action: (owner: AccountScope) => Promise<void>) => {
    if (pending.current) return;
    pending.current = true; setOperation(kind); setError(undefined);
    let owner: AccountScope | undefined;
    try { owner = scope(); await action(owner); }
    catch (caught) {
      if (live.current && (!owner || owner.isCurrent()) && !(caught instanceof AppleSignInCanceled) && !(caught instanceof GoogleSignInCanceled)) {
        setError(caught instanceof Error ? caught.message : 'Please try again.');
      }
    } finally { pending.current = false; if (live.current) setOperation(undefined); }
  };
  const openDeletion = () => {
    setDeleting(true); setConfirmed(false); setPreview(undefined);
    void run('preview', async owner => { const details = await getDeletionPreview(owner); if (owner.isCurrent()) setPreview(details); });
  };
  const closeDeletion = () => {
    if (pending.current) return;
    attempt.current += 1; setDeleting(false); setConfirmed(false); setError(undefined);
  };
  const remove = (provider: AccountProvider) => void run('delete', async owner => {
    await deleteVerifiedAccount(owner, provider);
    if (owner.isCurrent()) await finishAccountDeletion();
  });
  const providerNames = authProviders.map(provider => provider === 'apple' ? 'Apple' : 'Google').join(' and ');
  return <View style={s.account}>
    <Text style={s.overline}>ACCOUNT</Text>
    <Text selectable style={s.email}>{accountEmail}</Text>
    <View style={s.row}><Text style={s.note}>{demoSession ? 'Demo account · Sample travel data' : `Sign in with ${providerNames}`}</Text>
      <PressFeedback accessibilityRole="button" disabled={!!operation} onPress={() => void signOut()} style={s.textButton}><Text style={s.secondary}>Sign out</Text></PressFeedback>
    </View>
    {!demoSession && isAppleSignInEnabled() && !authProviders.includes('apple') ? <View>
      <PressFeedback accessibilityRole="button" disabled={!!operation} accessibilityState={{ busy: operation === 'link', disabled: !!operation }}
        onPress={() => void run('link', async owner => { await linkAppleAccount(owner); if (owner.isCurrent()) await refresh(); })} style={s.textButton}>
        {operation === 'link' ? <ActivityIndicator size="small" color={colors.blue} /> : null}
        <Text style={s.link}>{operation === 'link' ? 'Linking Apple…' : 'Link Apple sign-in'}</Text>
      </PressFeedback>
      <Text style={s.note}>Keep this account and all your trips. You may be asked to verify with Google first.</Text>
    </View> : null}
    {!demoSession ? <PressFeedback accessibilityRole="button" disabled={!!operation} onPress={openDeletion} style={s.textButton}><Text style={s.secondary}>Delete account</Text></PressFeedback> : null}
    {error && !deleting ? <Text accessibilityRole="alert" style={s.error}>{error}</Text> : null}
    {deleting ? <PlannerSheet title={confirmed ? 'Verify to delete' : 'Delete your account?'} transitionKey={`delete-account-${accountId}`} onClose={closeDeletion} error={error}>
      <View style={s.sheet}>
        <Text style={s.body}>Your Dreams, flight history and trips you organise will be permanently deleted. Other members will lose access to those trips.</Text>
        <Text style={s.body}>Places you shared to someone else’s trip will stay without your name. This cannot be undone.</Text>
        {operation === 'preview' ? <ActivityIndicator accessibilityLabel="Checking your account" color={colors.blue} /> : null}
        {preview ? <Text style={s.note}>{preview.owned_trips} {preview.owned_trips === 1 ? 'trip' : 'trips'} you organise{preview.shared_owned_trips ? ` · ${preview.shared_owned_trips} shared with others` : ''}</Text> : null}
        {!preview && !operation ? <PressFeedback accessibilityRole="button" onPress={openDeletion} style={s.action}><Text style={s.link}>Try again</Text></PressFeedback> : null}
        {preview && !confirmed ? <PressFeedback accessibilityRole="button" onPress={() => setConfirmed(true)} style={[s.action, s.destructive]}><Text style={s.destructiveLabel}>Delete account</Text></PressFeedback> : null}
        {preview && confirmed ? <>
          <Text style={s.body}>Verify your identity below to finish deleting this account.</Text>
          {operation === 'delete' ? <View style={s.progress} accessibilityLiveRegion="polite"><ActivityIndicator color={colors.blue} /><Text style={s.body}>Verifying and deleting…</Text></View> : <>
            {authProviders.includes('apple') ? <AppleSignInButton onPress={() => remove('apple')} unavailableMessage="Apple verification isn’t available on this device right now. Check that you’re signed in to your Apple Account, then try again." /> : null}
            {authProviders.includes('google') ? <PressFeedback accessibilityRole="button" onPress={() => remove('google')} style={s.action}><Text style={s.link}>Verify with Google</Text></PressFeedback> : null}
            {!authProviders.includes('google') && Platform.OS !== 'ios' ? <Text style={s.body}>Open Trotter on your iPhone to verify with Apple and delete your account.</Text> : null}
          </>}
        </> : null}
        <PressFeedback accessibilityRole="button" disabled={!!operation} onPress={closeDeletion} style={s.action}><Text style={s.secondary}>Keep my account</Text></PressFeedback>
      </View>
    </PlannerSheet> : null}
  </View>;
}

const s = StyleSheet.create({
  account: { borderTopWidth: 1, borderTopColor: colors.paperBorder, paddingTop: 21 },
  overline: { fontFamily: fonts.mono, fontSize: 10, lineHeight: 16, letterSpacing: .7, color: colors.mutedInk },
  email: { fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 21, color: colors.ink, marginTop: 9 },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  note: { fontFamily: fonts.sansRegular, fontSize: 11, lineHeight: 17, color: colors.mutedInk },
  textButton: { minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8 },
  secondary: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.mutedInk },
  link: { fontFamily: fonts.sansSemi, fontSize: 13, color: colors.blue },
  error: { fontFamily: fonts.sansRegular, fontSize: 12, lineHeight: 18, color: colors.redDeep },
  sheet: { gap: 16 }, body: { fontFamily: fonts.sansRegular, fontSize: 14, lineHeight: 22, color: colors.ink },
  action: { minHeight: 50, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3, padding: 12 },
  destructive: { backgroundColor: colors.redDeep, borderColor: colors.redDeep },
  destructiveLabel: { fontFamily: fonts.sansSemi, fontSize: 14, color: colors.paperSoft },
  progress: { flexDirection: 'row', gap: 12, alignItems: 'center' },
});
