export class AccountRequestError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message); this.name = 'AccountRequestError';
  }
}

const messages: Record<string, string> = {
  invalid_demo_credentials: 'That demo email and password do not match. Please try again.',
  demo_signin_unavailable: 'Demo sign-in is unavailable right now. Please try again later.',
  demo_signin_limited: 'Too many attempts. Wait a minute, then try again.',
  demo_personal_account_required: 'Use your own account to connect sign-in services or manage account deletion.',
  reauthentication_required: 'Please verify your identity again to continue.',
  account_deletion_retry: 'Your account could not be deleted yet. Please try again.',
  apple_account_already_linked: 'This Apple account is already linked to another Trotter account.',
  account_link_required: 'You already have a Trotter account. Sign in with your original method, then link Apple in Profile.',
  apple_signin_unavailable: 'Apple sign-in is not available right now. Please try again later.',
  apple_reauthentication_required: 'Verify with Apple to finish deleting this account.',
  invalid_apple_challenge: 'Apple sign-in expired. Please try again.',
  invalid_apple_credential: 'Apple sign-in could not be verified. Please try again.',
  reauth_wrong_account: 'Choose the account you currently use for Trotter. Nothing has been changed.',
};

export async function accountRequest<T>(base: string, path: string, options: { token?: string; method?: string; body?: unknown } = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`${base}${path}`, {
      method: options.method ?? 'GET', signal: controller.signal,
      headers: { ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
        ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
    });
    const text = await response.text();
    let data: any;
    try { data = text ? JSON.parse(text) : undefined; } catch { data = undefined; }
    if (!response.ok) {
      const code = typeof data?.detail === 'string' ? data.detail : 'request_failed';
      throw new AccountRequestError(response.status, code, messages[code] ?? (response.status === 409
        ? 'This sign-in belongs to another account. Sign in using your original method, then link Apple in Profile.'
        : response.status === 401 ? 'Your session has expired. Sign in again to continue.'
          : 'Trotter could not complete this request. Please try again.'));
    }
    return data as T;
  } catch (error) {
    if (error instanceof AccountRequestError) throw error;
    throw new Error('Trotter could not reach the server. Check your connection and try again.');
  } finally { clearTimeout(timeout); }
}
