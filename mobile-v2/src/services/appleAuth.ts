import { Platform } from 'react-native';
import { accountRequest } from './accountRequest';

export type AppleAuthPurpose = 'signin' | 'link' | 'reauth';
export type AccountAuthResult = { access_token: string; user_id: number; email: string; name?: string | null };
let sequence = 0;
let running = false;

export class AppleSignInCanceled extends Error {
  constructor() { super('Sign-in canceled.'); this.name = 'AppleSignInCanceled'; }
}
export function cancelAppleAuthSession() { sequence += 1; }

export async function requestAppleAuth(base: string, options: { purpose?: AppleAuthPurpose; token?: string; isCurrent?: () => boolean } = {}): Promise<AccountAuthResult> {
  if (Platform.OS !== 'ios') throw new Error('Apple sign-in is available in the iPhone app.');
  if (running) throw new Error('An Apple sign-in is already open. Finish or cancel it first.');
  const attempt = ++sequence;
  const current = () => attempt === sequence && (options.isCurrent?.() ?? true);
  const check = () => { if (!current()) throw new AppleSignInCanceled(); };
  running = true;
  try {
    const Apple = await import('expo-apple-authentication');
    if (!await Apple.isAvailableAsync()) throw new Error('Apple sign-in is not available on this device.');
    check();
    const purpose = options.purpose ?? 'signin';
    if (purpose !== 'signin' && !options.token) throw new Error('Sign in to Trotter before connecting Apple.');
    const challenge = await accountRequest<{ challenge_id: string; nonce: string }>(base, '/auth/apple/challenge', {
      token: options.token, method: 'POST', body: { purpose },
    });
    check();
    if (!challenge?.challenge_id || !challenge.nonce) throw new Error('Apple sign-in could not be started. Please try again.');
    const credential = await Apple.signInAsync({
      requestedScopes: [Apple.AppleAuthenticationScope.FULL_NAME, Apple.AppleAuthenticationScope.EMAIL],
      nonce: challenge.nonce, state: challenge.challenge_id,
    });
    check();
    if (credential.state !== challenge.challenge_id || !credential.identityToken || !credential.authorizationCode) {
      throw new Error('Apple sign-in could not be verified. Please try again.');
    }
    const name = credential.fullName ? Apple.formatFullName(credential.fullName).trim() : undefined;
    const result = await accountRequest<AccountAuthResult>(base, '/auth/apple', {
      token: options.token, method: 'POST', body: { challenge_id: challenge.challenge_id,
        identity_token: credential.identityToken, authorization_code: credential.authorizationCode,
        ...(name ? { name: name.slice(0, 200) } : {}) },
    });
    check();
    if (!result?.access_token || /\s/.test(result.access_token) || !Number.isSafeInteger(result.user_id) || result.user_id < 1) {
      throw new Error('Apple sign-in did not return a valid account. Please try again.');
    }
    return result;
  } catch (error) {
    if (!current() || (error as { code?: string })?.code === 'ERR_REQUEST_CANCELED') throw new AppleSignInCanceled();
    throw error;
  } finally { running = false; }
}
