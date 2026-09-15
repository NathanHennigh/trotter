import * as THREE from 'three';
import { ExpoTextureLoader } from '../../lib/expoThree';

function cancelled() { const error = new Error('Globe initialization cancelled'); error.name = 'AbortError'; return error; }

/** Resolve a texture before drawing it; retries are bounded and stale callbacks own no GPU resources. */
export async function loadGlobeTexture(asset: number, signal?: AbortSignal, attempts = 2): Promise<THREE.Texture> {
  let failure: unknown;
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (signal?.aborted) throw cancelled();
    try {
      return await new Promise<THREE.Texture>((resolve, reject) => {
        let texture: THREE.Texture | undefined, finished = false, succeeded = false, disposed = false;
        const dispose = () => { if (texture && !disposed) { disposed = true; texture.dispose(); } };
        const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); };
        const fail = (error: unknown) => {
          if (finished) return;
          finished = true; cleanup(); dispose(); reject(error);
        };
        const abort = () => fail(cancelled());
        const timer = setTimeout(() => fail(new Error('Globe texture loading timed out')), 8000);
        signal?.addEventListener('abort', abort, { once: true });
        try {
          texture = new ExpoTextureLoader().load(asset, value => {
            texture ??= value;
            if (finished) { dispose(); return; }
            finished = succeeded = true; cleanup(); resolve(value);
          }, undefined, fail);
          if (finished && !succeeded) dispose();
        } catch (error) { fail(error); }
      });
    } catch (error) { failure = error; if (signal?.aborted) throw cancelled(); }
  }
  throw failure;
}

type BaseSource = { primary: number; fallback: number };
export type GlobeBaseSources = { day: BaseSource; night: BaseSource; index: BaseSource };
export async function loadGlobeBaseTextures(
  sources: GlobeBaseSources,
  signal: AbortSignal,
  load: typeof loadGlobeTexture = loadGlobeTexture,
) {
  const owned: THREE.Texture[] = [];
  let failed = false;
  const acquire = async (source: BaseSource) => {
    let texture: THREE.Texture;
    try { texture = await load(source.primary, signal); }
    catch (error) {
      if (signal.aborted || source.primary === source.fallback) throw error;
      texture = await load(source.fallback, signal);
    }
    if (failed || signal.aborted) { texture.dispose(); throw cancelled(); }
    owned.push(texture); return texture;
  };
  try {
    const [day, night, index] = await Promise.all([acquire(sources.day), acquire(sources.night), acquire(sources.index)]);
    return { day, night, index };
  } catch (error) {
    failed = true; owned.forEach(texture => texture.dispose()); throw error;
  }
}
