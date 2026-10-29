const fs = require('node:fs');
const path = require('node:path');
const { withDangerousMod } = require('@expo/config-plugins');

const marker = '// Trotter: asynchronous software-renderer frame barrier.';
const anchor = '# pragma mark - Headless Context';
const method = `${marker}
// Runs behind endFrameEXP's queued drawing, without blocking the JS/UI threads.
EX_EXPORT_METHOD_AS(trotterWaitForFrameAsync,
                    trotterWaitForFrameWithContextId:(nonnull NSNumber *)contextId
                    resolver:(EXPromiseResolveBlock)resolve
                    rejecter:(EXPromiseRejectBlock)reject)
{
  EXGLContext *context = [self getContextWithId:contextId];
  if (context == nil || ![context isInitialized]) {
    reject(@"E_GL_CONTEXT_UNAVAILABLE", @"The globe context is no longer available.", nil);
    return;
  }
  [context runAsync:^{ resolve(@YES); }];
}

`;

function patchFrameBarrier(source) {
  if (source.includes(marker)) {
    if (!source.includes(method)) throw new Error('The Trotter GL frame barrier differs from its maintained implementation.');
    return source;
  }
  if (source.split(anchor).length !== 2 || !source.includes('- (EXGLContext *)getContextWithId:')) {
    throw new Error('expo-gl changed its native context manager; review the frame barrier before upgrading.');
  }
  return source.replace(anchor, method + anchor);
}

module.exports = config => withDangerousMod(config, ['ios', async config => {
  const root = config.modRequest.projectRoot;
  const manifest = require.resolve('expo-gl/package.json', { paths: [root] });
  const version = JSON.parse(fs.readFileSync(manifest, 'utf8')).version;
  if (version !== '16.0.10') throw new Error(`Review Trotter's GL frame barrier for expo-gl ${version}.`);
  const file = path.join(path.dirname(manifest), 'ios', 'EXGLObjectManager.mm');
  const original = fs.readFileSync(file, 'utf8');
  const next = patchFrameBarrier(original);
  if (next !== original) fs.writeFileSync(file, next);
  return config;
}]);
module.exports.patchFrameBarrier = patchFrameBarrier;
