import { NativeModules, Platform } from 'react-native';

export type NativeDreamShareReceipt = {
  id: string;
  sourceUrl: string;
  sharedText?: string;
  ownerId?: number;
  status: 'queued' | 'uploading' | 'saved' | 'sign_in' | 'failed';
  itemId?: number;
  dreamId?: number;
  message?: string;
  createdAt: number;
};
type NativeShareBridge = {
  invalidateSession(revision: number): Promise<void>;
  configureSession(apiBaseUrl: string, ownerId: number, token: string, revision: number): Promise<void>;
  listReceipts(): Promise<NativeDreamShareReceipt[]>;
  flush(): Promise<void>;
  retry(id: string): Promise<void>;
  acknowledge(id: string): Promise<void>;
};
const nativeBridge = (): NativeShareBridge | undefined => Platform.OS === 'android' ? NativeModules.TrotterDreamShare : undefined;

/** Pass the same auth revision to invalidation and the subsequent verified /auth/me identity. */
export async function invalidateNativeDreamShareSession(revision: number): Promise<void> {
  await nativeBridge()?.invalidateSession(revision);
}
export async function syncNativeDreamShareSession(session: { apiBaseUrl: string; ownerId: number; token: string }, revision: number): Promise<void> {
  await nativeBridge()?.configureSession(session.apiBaseUrl, session.ownerId, session.token, revision);
}
export async function listNativeDreamShareReceipts(): Promise<NativeDreamShareReceipt[]> {
  return await nativeBridge()?.listReceipts() ?? [];
}
export async function flushNativeDreamShares(): Promise<void> { await nativeBridge()?.flush(); }
export async function retryNativeDreamShare(id: string): Promise<void> { await nativeBridge()?.retry(id); }
/** Call only after a successful authoritative Dreams refresh. Pending captures are never removed. */
export async function acknowledgeNativeDreamShare(id: string): Promise<void> { await nativeBridge()?.acknowledge(id); }
