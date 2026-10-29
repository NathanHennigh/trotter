import AsyncStorage from '@react-native-async-storage/async-storage';
import { dreamShareOutbox, type DreamShareOutboxOwner } from './dreamShareOutbox';
import { clearGmailRecovery } from './gmailRecovery';
import { clearTravelerIdentity } from '../utils/travelerIdentity';
import { forgetNativeDreamShareAccount } from './nativeDreamShare';

const KEY = 'trotter.account-erasure.pending.v1';
let pendingOwner: DreamShareOutboxOwner | undefined;

/** Called only after the server confirms deletion; no tokens are stored here. */
export function markDeletedAccountForCleanup(owner: DreamShareOutboxOwner) { pendingOwner = owner; }
export async function hasDeletedAccountCleanup() { return !!pendingOwner || !!await AsyncStorage.getItem(KEY); }

/** Keep a retry marker until every device store has acknowledged the erasure. */
export async function finishDeletedAccountCleanup() {
  if (pendingOwner) await AsyncStorage.setItem(KEY, JSON.stringify(pendingOwner));
  const raw = pendingOwner ? JSON.stringify(pendingOwner) : await AsyncStorage.getItem(KEY);
  if (!raw) return;
  const owner = JSON.parse(raw) as DreamShareOutboxOwner;
  if (!Number.isSafeInteger(owner.ownerId) || owner.ownerId <= 0 || typeof owner.apiBaseUrl !== 'string') throw new Error('Account cleanup needs attention.');
  const api = new URL(owner.apiBaseUrl);
  if (!['https:', 'http:'].includes(api.protocol) || api.username || api.password || api.search || api.hash) throw new Error('Account cleanup needs attention.');
  const results = await Promise.allSettled([
    forgetNativeDreamShareAccount(owner.apiBaseUrl, owner.ownerId), dreamShareOutbox.clear(owner),
    clearGmailRecovery(owner.apiBaseUrl, owner.ownerId), clearTravelerIdentity(`${owner.apiBaseUrl}/${owner.ownerId}`),
  ]);
  if (results.some(result => result.status === 'rejected')) throw new Error('Saved account data could not be cleared from this device. Retry sign out to finish.');
  await AsyncStorage.removeItem(KEY);
  pendingOwner = undefined;
}
