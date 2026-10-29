import React from 'react';
import { ActivityIndicator, Text, View } from 'react-native';
import * as Apple from 'expo-apple-authentication';
import { PressFeedback } from '../motion';
import { colors, fonts } from '../../../theme/trotterTheme';

export type AppleSignInButtonProps = { onPress: () => void; disabled?: boolean; unavailableMessage?: string; appearance?: 'black' | 'outline' };
export function AppleSignInButton({ onPress, disabled = false, unavailableMessage, appearance = 'black' }: AppleSignInButtonProps) {
  const [available, setAvailable] = React.useState<boolean>(), [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setAvailable(undefined);
    void Apple.isAvailableAsync().then(value => { if (live) setAvailable(value); }).catch(() => { if (live) setAvailable(false); });
    return () => { live = false; };
  }, [retry]);
  if (!available) return !unavailableMessage ? null : available === undefined
    ? <ActivityIndicator accessibilityLabel="Checking Apple sign-in" color={colors.blue} />
    : <View style={{ gap: 8 }}><Text accessibilityRole="alert" style={{ fontFamily: fonts.sansRegular, fontSize: 13, lineHeight: 20, color: colors.mutedInk }}>{unavailableMessage}</Text>
      <PressFeedback accessibilityRole="button" onPress={() => setRetry(value => value + 1)} style={{ minHeight: 44, justifyContent: 'center' }}><Text style={{ color: colors.blue, fontFamily: fonts.sansSemi }}>Try Apple again</Text></PressFeedback></View>;
  return <View pointerEvents={disabled ? 'none' : 'auto'} accessibilityState={{ disabled }} style={{ opacity: disabled ? .5 : 1, ...(appearance === 'outline' ? { borderTopWidth: 1, borderTopColor: colors.paperBorder, paddingTop: 16, marginTop: 4 } : {}) }}>
    <Apple.AppleAuthenticationButton buttonType={Apple.AppleAuthenticationButtonType.CONTINUE}
      buttonStyle={appearance === 'outline' ? Apple.AppleAuthenticationButtonStyle.WHITE_OUTLINE : Apple.AppleAuthenticationButtonStyle.BLACK} cornerRadius={3}
      style={{ width: '100%', height: 54 }} onPress={() => { if (!disabled) onPress(); }} />
  </View>;
}
