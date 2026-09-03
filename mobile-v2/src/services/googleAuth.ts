import { Linking, Platform } from 'react-native';

export async function requestGoogleAuthToken(apiBaseUrl: string) {
  const redirectUri = getOAuthRedirectUri();
  const startUrl = `${apiBaseUrl}/auth/google/start?app_redirect_uri=${encodeURIComponent(redirectUri)}`;

  if (Platform.OS === 'web') {
    const browser = globalThis as typeof globalThis & { location?: { assign: (url: string) => void } };
    if (!browser.location) throw new Error('Web sign-in requires a browser location.');
    browser.location.assign(startUrl);
    return new Promise<never>(() => undefined);
  }

  const callbackUrl = await openExternalAuthSession(startUrl, redirectUri);
  const token = readQueryParam(callbackUrl, 'token');
  if (!token) {
    throw new Error('Google sign-in completed, but no app token was returned.');
  }
  return token;
}

function getOAuthRedirectUri() {
  if (Platform.OS !== 'web') return 'trotterv2://oauthredirect';
  const browser = globalThis as typeof globalThis & { location?: { origin?: string } };
  if (!browser.location?.origin) throw new Error('Web sign-in requires a browser origin.');
  return `${browser.location.origin}/oauthredirect`;
}

function openExternalAuthSession(startUrl: string, redirectUri: string) {
  return new Promise<string>((resolve, reject) => {
    let settled = false;
    let subscription: { remove: () => void } | undefined;
    const timeout = setTimeout(
      () => finish(undefined, new Error('Google sign-in timed out before Trotter received a token.')),
      10 * 60 * 1000,
    );

    const finish = (url?: string, error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      subscription?.remove();
      if (error) reject(error);
      else resolve(url ?? '');
    };

    subscription = Linking.addEventListener('url', ({ url }) => {
      if (url.startsWith(redirectUri) || readQueryParam(url, 'token')) finish(url);
    });

    Linking.openURL(startUrl).catch((error) => {
      finish(undefined, error instanceof Error ? error : new Error(String(error)));
    });
  });
}

function readQueryParam(url: string, key: string) {
  try {
    return new URL(url).searchParams.get(key) ?? undefined;
  } catch {
    const match = new RegExp(`[?&]${key}=([^&]+)`).exec(url);
    return match ? decodeURIComponent(match[1]) : undefined;
  }
}
