import React from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

const keyFor = (owner: string) => `trotter.traveler-identity.v1.${encodeURIComponent(owner)}`;
let writes: Promise<unknown> = Promise.resolve();
export async function readHomeAirport(owner: string): Promise<string | undefined> {
  await writes.catch(() => undefined);
  const raw = await AsyncStorage.getItem(keyFor(owner));
  if (!raw) return undefined;
  try {
    const saved = JSON.parse(raw);
    return typeof saved?.homeAirport === 'string' && /^[A-Z]{3}$/.test(saved.homeAirport) ? saved.homeAirport : undefined;
  } catch { return undefined; }
}
export function writeHomeAirport(owner: string, code?: string): Promise<void> {
  if (code != null && !/^[A-Z]{3}$/.test(code)) return Promise.reject(new Error('Choose a valid airport.'));
  const pending = writes.catch(() => undefined).then(() => AsyncStorage.setItem(keyFor(owner), JSON.stringify({ homeAirport: code ?? null })));
  writes = pending;
  return pending;
}

/** Personal display preferences are isolated by server and signed-in account. */
export function useTravelerIdentity(owner?: string) {
  const [snapshot, setSnapshot] = React.useState<{ owner?: string; code?: string; ready: boolean; error?: string }>({ ready: false });
  const ownerRef = React.useRef(owner);
  const alive = React.useRef(true);
  ownerRef.current = owner;
  React.useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  React.useEffect(() => {
    let live = true;
    if (!owner) { setSnapshot({ ready: false }); return; }
    void readHomeAirport(owner).then(code => { if (live) setSnapshot({ owner, code, ready: true }); })
      .catch(() => { if (live) setSnapshot({ owner, ready: true, error: 'Your saved home airport could not be loaded.' }); });
    return () => { live = false; };
  }, [owner]);
  const homeAirport = snapshot.owner === owner ? snapshot.code : undefined;
  const ready = Boolean(owner && snapshot.owner === owner && snapshot.ready);
  const setHomeAirport = async (code?: string) => {
    if (!owner || !ready) throw new Error('Wait for your profile to load.');
    await writeHomeAirport(owner, code);
    if (alive.current && ownerRef.current === owner) setSnapshot({ owner, code, ready: true });
  };
  return { homeAirport, ready, error: snapshot.owner === owner ? snapshot.error : undefined, setHomeAirport };
}
