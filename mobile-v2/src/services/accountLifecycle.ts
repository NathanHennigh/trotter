import { accountRequest, AccountRequestError } from './accountRequest';
import { requestAppleAuth } from './appleAuth';
import { GoogleSignInCanceled, requestGoogleReauthentication } from './googleAuth';

export type AccountProvider = 'google' | 'apple';
export type AccountScope = { base: string; token: string; ownerId: number; isCurrent: () => boolean };
export type DeletionPreview = { owned_trips: number; shared_owned_trips: number };
function check(scope: AccountScope) { if (!scope.isCurrent()) throw new GoogleSignInCanceled(); }

export async function reauthenticateAccount(scope: AccountScope, provider: AccountProvider) {
  check(scope);
  const token = provider === 'apple'
    ? (await requestAppleAuth(scope.base, { purpose: 'reauth', token: scope.token, isCurrent: scope.isCurrent })).access_token
    : await requestGoogleReauthentication(async redirect => {
      check(scope);
      const result = await accountRequest<{ url: string }>(scope.base, '/auth/google/reauth/start', {
        token: scope.token, method: 'POST', body: { app_redirect_uri: redirect },
      });
      check(scope);
      const url = new URL(result.url);
      if (url.origin !== 'https://accounts.google.com' || url.pathname !== '/o/oauth2/v2/auth' || url.username || url.password) {
        throw new Error('Account verification could not be started. Please try again.');
      }
      return result.url;
    });
  check(scope);
  // Never replace the running app's session with a verification result.
  const verified = await accountRequest<{ user_id: number }>(scope.base, '/auth/me', { token });
  check(scope);
  if (verified.user_id !== scope.ownerId) throw new Error('Choose your current Trotter account. Nothing has been changed.');
  return token;
}

export async function linkAppleAccount(scope: AccountScope) {
  check(scope);
  let token = scope.token;
  try {
    const result = await requestAppleAuth(scope.base, { purpose: 'link', token, isCurrent: scope.isCurrent });
    check(scope);
    if (result.user_id !== scope.ownerId) throw new Error('Apple could not be linked to this account.');
    return;
  } catch (error) {
    if (!(error instanceof AccountRequestError) || error.code !== 'reauthentication_required') throw error;
  }
  token = await reauthenticateAccount(scope, 'google');
  check(scope);
  const result = await requestAppleAuth(scope.base, { purpose: 'link', token, isCurrent: scope.isCurrent });
  check(scope);
  if (result.user_id !== scope.ownerId) throw new Error('Apple could not be linked to this account.');
}

export async function deleteVerifiedAccount(scope: AccountScope, provider: AccountProvider) {
  const token = await reauthenticateAccount(scope, provider);
  check(scope);
  await accountRequest<void>(scope.base, '/auth/account', { token, method: 'DELETE', body: { confirmation: 'DELETE' } });
}

export async function getDeletionPreview(scope: AccountScope) {
  check(scope);
  const result = await accountRequest<DeletionPreview>(scope.base, '/auth/account/deletion-preview', { token: scope.token });
  check(scope);
  if (!Number.isSafeInteger(result?.owned_trips) || result.owned_trips < 0
      || !Number.isSafeInteger(result.shared_owned_trips) || result.shared_owned_trips < 0
      || result.shared_owned_trips > result.owned_trips) throw new Error('Your account details could not be checked. Please try again.');
  return result;
}
