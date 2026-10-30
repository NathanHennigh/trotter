const fs = require('node:fs');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

function parseOrigin(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('An explicit HTTP(S) API origin is required.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('The API must be an HTTP(S) origin without credentials, path, query, or fragment.');
  }
  return url.origin;
}

async function checkReadiness(value, request = fetch) {
  const origin = parseOrigin(value);
  const response = await request(`${origin}/ready`, { redirect: 'error', signal: AbortSignal.timeout(15000) });
  if (response.status !== 200 || !response.headers.get('content-type')?.toLowerCase().includes('application/json')) {
    throw new Error(`API preflight failed for ${origin}: /ready must return HTTP200 JSON.`);
  }
  if (response.url && new URL(response.url).origin !== origin) throw new Error('API preflight changed origin.');
  const body = await response.json();
  if (body?.status !== 'ready' || body?.checks?.database !== true || body?.checks?.redis !== true) {
    throw new Error(`API preflight failed for ${origin}: database and Redis must both be ready.`);
  }
  return { api_origin: origin, checked_at: new Date().toISOString(), readiness: body };
}

function artifactMetadata({ artifact, bundle, readiness, commit, versionCode, channel }) {
  const origin = parseOrigin(readiness.api_origin);
  if (!bundle.includes(Buffer.from(origin))) {
    throw new Error(`Packaged JavaScript does not contain the verified API origin ${origin}; refusing to publish.`);
  }
  if (!Number.isInteger(versionCode) || versionCode <= 0) throw new Error('Invalid artifact version code.');
  return { schema_version: 1, package: 'com.trotter.mobilev2', version_code: versionCode,
    api_origin: origin, api_preflight: readiness, bundle_origin_verified: true,
    source_commit: commit, channel, built_at: new Date().toISOString(),
    sha256: crypto.createHash('sha256').update(artifact).digest('hex') };
}

async function main(args) {
  if (args[0] === 'check') {
    process.stdout.write(JSON.stringify(await checkReadiness(args[1])));
  } else if (args[0] === 'metadata') {
    const [, artifactPath, outputPath, commit, version, channel, readinessJson] = args;
    const bundleEntry = artifactPath.endsWith('.aab') ? 'base/assets/index.android.bundle' : 'assets/index.android.bundle';
    const bundle = execFileSync('unzip', ['-p', artifactPath, bundleEntry], { maxBuffer: 128 * 1024 * 1024 });
    const metadata = artifactMetadata({ artifact: fs.readFileSync(artifactPath), bundle,
      readiness: JSON.parse(readinessJson), commit, versionCode: Number(version), channel });
    fs.writeFileSync(outputPath, `${JSON.stringify(metadata, null, 2)}\n`);
    console.log(`Verified packaged API: ${metadata.api_origin}`);
  } else throw new Error('Expected check or metadata command.');
}
module.exports = { parseOrigin, checkReadiness, artifactMetadata };
if (require.main === module) main(process.argv.slice(2)).catch(error => {
  console.error(`Android build API validation failed: ${error.message}`); process.exitCode = 1;
});
