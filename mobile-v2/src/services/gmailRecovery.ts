import AsyncStorage from '@react-native-async-storage/async-storage';

// Recovery metadata only. Tokens and mailbox content never enter this store.
export type GmailRecovery = {
  version: 1;
  apiBaseUrl: string;
  ownerId: number;
  lastSuccessAt?: string;
  activeJobId?: string;
  activeStartedAt?: string;
  outcome?: 'synced' | 'error';
};
let writes: Promise<unknown> = Promise.resolve();
const key = (api: string, owner: number) => `trotter.gmail-recovery.v1.${encodeURIComponent(api)}.${owner}`;
const validDate = (value: unknown) => typeof value === 'string' && Number.isFinite(Date.parse(value)) && Date.parse(value) <= Date.now() + 60000;

export async function readGmailRecovery(apiBaseUrl: string, ownerId: number): Promise<GmailRecovery | undefined> {
  await writes.catch(() => undefined);
  try {
    const raw = await AsyncStorage.getItem(key(apiBaseUrl, ownerId));
    if (!raw) return undefined;
    const value = JSON.parse(raw) as GmailRecovery;
    if (value.version !== 1 || value.apiBaseUrl !== apiBaseUrl || value.ownerId !== ownerId) return undefined;
    const activeJobId = typeof value.activeJobId === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(value.activeJobId)
      && validDate(value.activeStartedAt) && Date.now() - Date.parse(value.activeStartedAt!) < 7 * 86400000 ? value.activeJobId : undefined;
    return { version: 1, apiBaseUrl, ownerId,
      lastSuccessAt: validDate(value.lastSuccessAt) ? value.lastSuccessAt : undefined,
      activeJobId, activeStartedAt: activeJobId ? value.activeStartedAt : undefined,
      outcome: value.outcome === 'synced' || value.outcome === 'error' ? value.outcome : undefined };
  } catch { return undefined; }
}

export function writeGmailRecovery(value: GmailRecovery): Promise<void> {
  const snapshot = JSON.stringify(value);
  const pending = writes.catch(() => undefined).then(() => AsyncStorage.setItem(key(value.apiBaseUrl, value.ownerId), snapshot));
  writes = pending;
  return pending;
}
