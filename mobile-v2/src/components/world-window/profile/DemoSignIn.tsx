import React from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import { PlannerAction, PlannerSheet } from '../planner/PlannerKit';
import { colors, fonts } from '../../../theme/trotterTheme';

export function DemoSignIn({ busy, error, onClose, onSubmit }: {
  busy: boolean; error?: string; onClose: () => void; onSubmit: (email: string, password: string) => void;
}) {
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const passwordField = React.useRef<TextInput>(null);
  const ready = Boolean(email.trim() && password && !busy);
  const submit = () => { if (ready) { onSubmit(email.trim(), password); setPassword(''); } };
  return <PlannerSheet title="Demo sign-in" subtitle="Explore Trotter with sample trips." onClose={onClose} error={error}
    footer={<PlannerAction label={busy ? 'Opening demo…' : 'Open demo'} onPress={submit} disabled={!ready} busy={busy} />}>
    <View style={s.form}>
      <View style={s.field}><Text style={s.label}>Email</Text><TextInput accessibilityLabel="Demo email" value={email} onChangeText={setEmail}
        autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="username" autoComplete="username"
        returnKeyType="next" onSubmitEditing={() => passwordField.current?.focus()} editable={!busy} maxLength={254} style={s.input} /></View>
      <View style={s.field}><Text style={s.label}>Password</Text><TextInput ref={passwordField} accessibilityLabel="Demo password" value={password} onChangeText={setPassword}
        secureTextEntry autoCapitalize="none" autoCorrect={false} textContentType="password" autoComplete="current-password"
        returnKeyType="go" onSubmitEditing={submit} editable={!busy} maxLength={128} style={s.input} /></View>
    </View>
  </PlannerSheet>;
}
const s = StyleSheet.create({
  form: { gap: 18 }, field: { gap: 7 },
  label: { fontFamily: fonts.sansSemi, fontSize: 12, color: colors.ink },
  input: { minHeight: 50, paddingHorizontal: 12, borderWidth: 1, borderColor: colors.paperBorder, borderRadius: 3,
    backgroundColor: colors.paper, color: colors.ink, fontFamily: fonts.sansRegular, fontSize: 16 },
});
