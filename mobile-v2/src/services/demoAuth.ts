import { accountRequest } from './accountRequest';
import type { AccountAuthResult } from './appleAuth';

export async function requestDemoAuth(base: string, email: string, password: string): Promise<AccountAuthResult> {
  const result = await accountRequest<AccountAuthResult>(base, '/auth/demo', {
    method: 'POST', body: { email: email.trim(), password },
  });
  if (!result?.access_token || /\s/.test(result.access_token) || !Number.isSafeInteger(result.user_id) || result.user_id < 1) {
    throw new Error('Demo sign-in could not be verified. Please try again.');
  }
  return result;
}
