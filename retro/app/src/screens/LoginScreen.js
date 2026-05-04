import React, { useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Alert,
} from 'react-native';
import * as WebBrowser from 'expo-web-browser';
import * as Linking from 'expo-linking';
import { useAuthStore }     from '../store/useAuthStore';
import { getDevToken, buildGoogleStartUrl } from '../api/auth';

WebBrowser.maybeCompleteAuthSession();

/**
 * DEV_BYPASS:
 *   true  → "SKIP AUTH" button uses backend /auth/dev-token (real JWT, real API calls)
 *   false → only the Google sign-in button is shown (production)
 *
 * Requires DEV_MODE=true in backend .env when DEV_BYPASS=true.
 */
const DEV_BYPASS = true;

const BOOT_LINES = [
  '> UNIT NOT REGISTERED',
  '> AWAITING AUTHENTICATION',
  '> GMAIL ACCESS REQUIRED',
  '> INITIATE SIGN-IN TO PROCEED',
];

export default function LoginScreen() {
  const login = useAuthStore(s => s.login);
  const [loading, setLoading] = useState(false);
  const [lines, setLines]     = useState([0]);

  React.useEffect(() => {
    const id = setInterval(() =>
      setLines(l => l.length < BOOT_LINES.length ? [...l, l.length] : l), 500);
    return () => clearInterval(id);
  }, []);

  // ── Dev bypass — calls /auth/dev-token → real JWT ──────────────────────────
  const handleDevBypass = async () => {
    setLoading(true);
    try {
      const result = await getDevToken();
      await login(result);
    } catch (e) {
      Alert.alert(
        'DEV TOKEN ERROR',
        `${e.message}\n\nMake sure the backend is running and DEV_MODE=true is set in backend/.env`,
      );
    } finally {
      setLoading(false);
    }
  };

  // ── Google OAuth via backend web flow — no native modules needed ───────────
  const handleGoogleSignIn = async () => {
    setLoading(true);
    try {
      // The backend will redirect to this URL after OAuth completes
      const appRedirectUri = Linking.createURL('auth/callback');
      const startUrl       = buildGoogleStartUrl(appRedirectUri);

      const result = await WebBrowser.openAuthSessionAsync(startUrl, appRedirectUri);

      if (result.type !== 'success') {
        setLoading(false);
        return; // User cancelled
      }

      // Parse the JWT from the redirect URL  e.g. trotter://auth/callback?token=...
      const parsed = Linking.parse(result.url);
      const token  = parsed.queryParams?.token;
      if (!token) throw new Error('No token returned from OAuth flow');

      // Fetch user info with the token, then store
      const resp = await fetch(
        `${(await import('../api/config')).BASE_URL}/auth/me`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!resp.ok) throw new Error('Failed to validate token');
      const user = await resp.json();

      await login({
        access_token: token,
        user_id: user.user_id,
        email:   user.email,
        name:    user.name,
      });
    } catch (e) {
      Alert.alert('SIGN-IN ERROR', e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={s.shell}>
      <View style={s.crt}>
        <Text style={s.logo}>TROTTER</Text>
        <Text style={s.subLogo}>TRAVEL DECK MK-II</Text>

        <View style={s.terminal}>
          {BOOT_LINES.map((line, i) => (
            <Text key={i} style={[s.termLine, lines.includes(i) && s.termLineVis]}>
              {line}
            </Text>
          ))}
        </View>

        <View style={s.divider} />

        {/* Dev bypass button */}
        {DEV_BYPASS && (
          <TouchableOpacity
            style={[s.btnBase, s.btnDev, loading && { opacity: 0.5 }]}
            onPress={handleDevBypass}
            disabled={loading}
            activeOpacity={0.8}
          >
            {loading
              ? <ActivityIndicator color="#fff" size="small" />
              : <Text style={s.btnTxt}>▶  SKIP AUTH  (DEV)</Text>
            }
          </TouchableOpacity>
        )}

        {/* Google sign-in button */}
        <TouchableOpacity
          style={[s.btnBase, s.btnGoogle, loading && { opacity: 0.5 }]}
          onPress={handleGoogleSignIn}
          disabled={loading}
          activeOpacity={0.8}
        >
          {loading && !DEV_BYPASS
            ? <ActivityIndicator color="#fff" size="small" />
            : (
              <>
                <Text style={s.gLetter}>[G]</Text>
                <Text style={s.btnTxt}> SIGN IN WITH GOOGLE</Text>
              </>
            )
          }
        </TouchableOpacity>

        {DEV_BYPASS && (
          <Text style={s.noteText}>DEV BYPASS = backend /auth/dev-token (DEV_MODE=true)</Text>
        )}

        <Text style={s.cautionText}>
          {'⚠  CAUTION: GMAIL READ ACCESS\n   REQUIRED FOR FLIGHT SYNC'}
        </Text>
      </View>

      {/* Beige hardware panel */}
      <View style={s.panel}>
        <View style={s.speakerRow}>
          {Array.from({ length: 36 }).map((_, i) => <View key={i} style={s.dot} />)}
        </View>
        <View style={s.stickersRow}>
          <View style={s.warnSticker}>
            <Text style={s.warnTxt}>⚠ CAUTION: DATA LINK</Text>
          </View>
          <View style={{ flex: 1 }} />
          <View style={s.serialSticker}>
            <Text style={s.serialTxt}>S/N TR0TT-MK2</Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const GREEN = '#6ab04c', GREEN_DIM = '#2d5a1b', BEIGE = '#d4c8a8';

const s = StyleSheet.create({
  shell:    { flex: 1, backgroundColor: BEIGE },
  crt:      { flex: 1, backgroundColor: '#050c03', padding: 28, alignItems: 'center', justifyContent: 'center' },
  logo:     { fontFamily: 'SpaceMono', fontSize: 32, fontWeight: '900', letterSpacing: 8, color: GREEN,
              textShadowColor: 'rgba(106,180,76,0.5)', textShadowOffset: { width: 0, height: 0 }, textShadowRadius: 16, marginBottom: 4 },
  subLogo:  { fontFamily: 'SpaceMono', fontSize: 9, letterSpacing: 5, color: GREEN_DIM, marginBottom: 32 },
  terminal: { width: '100%', marginBottom: 24 },
  termLine: { fontFamily: 'SpaceMono', fontSize: 11, color: GREEN_DIM, lineHeight: 22, opacity: 0 },
  termLineVis: { opacity: 1, color: GREEN },
  divider:  { width: '100%', height: 1, backgroundColor: GREEN_DIM, marginBottom: 24, opacity: 0.4 },
  btnBase:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
              width: '100%', paddingVertical: 14, borderRadius: 6,
              shadowOffset: { width: 0, height: 4 }, shadowOpacity: 1, shadowRadius: 0, elevation: 8, marginBottom: 10 },
  btnDev:    { backgroundColor: '#e8006f', shadowColor: '#8a0040' },
  btnGoogle: { backgroundColor: '#1a1a1a', shadowColor: '#000' },
  btnTxt:    { fontFamily: 'SpaceMono', fontSize: 11, fontWeight: '900', letterSpacing: 2, color: '#fff' },
  gLetter:   { fontFamily: 'SpaceMono', fontSize: 14, fontWeight: '900', color: '#fff' },
  noteText:  { fontFamily: 'SpaceMono', fontSize: 7, color: '#2d5a1b', opacity: 0.7, textAlign: 'center', marginBottom: 16, letterSpacing: 1 },
  cautionText: { fontFamily: 'SpaceMono', fontSize: 8, letterSpacing: 2, color: GREEN_DIM, textAlign: 'center', lineHeight: 16 },
  panel:     { backgroundColor: BEIGE, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 24 },
  speakerRow:{ flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginBottom: 10 },
  dot:       { width: 5, height: 5, borderRadius: 3, backgroundColor: '#2a2415' },
  stickersRow: { flexDirection: 'row', alignItems: 'center' },
  warnSticker: { backgroundColor: '#f5c800', borderWidth: 1, borderColor: '#b09500', paddingHorizontal: 6, paddingVertical: 2 },
  warnTxt:   { fontFamily: 'SpaceMono', fontSize: 6, fontWeight: '900', letterSpacing: 2, color: '#1a1000' },
  serialSticker: { backgroundColor: '#d8d8d8', borderWidth: 1, borderColor: '#909090', paddingHorizontal: 6, paddingVertical: 2 },
  serialTxt: { fontFamily: 'SpaceMono', fontSize: 6, color: '#2a2a2a' },
});
