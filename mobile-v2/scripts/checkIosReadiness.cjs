const fs = require('node:fs');
const path = require('node:path');

function checkIosReadiness(config, env, { local = false, simulator = false, root = path.resolve(__dirname, '..') } = {}) {
  const errors = [], notes = [];
  if (!local && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(config.extra?.eas?.projectId || '')) {
    errors.push('Link the real Expo project (eas init) or set EAS_PROJECT_ID.');
  }
  if (!simulator && !/^[A-Z0-9]{10}$/.test(config.ios?.appleTeamId || '')) {
    errors.push('Set APPLE_TEAM_ID for signing the app and Instagram share extension.');
  }
  if (!config.ios?.usesAppleSignIn) errors.push('Enable ios.usesAppleSignIn.');
  if (config.ios?.supportsTablet !== false) errors.push('This release targets iPhone; disable unverified iPad support.');
  if (!config.extra?.googleMapsIosConfigured) errors.push('Set GOOGLE_MAPS_IOS_API_KEY to an iOS-restricted Maps SDK key.');
  const pluginNames = (config.plugins || []).map(plugin => Array.isArray(plugin) ? plugin[0] : plugin);
  for (const plugin of ['expo-apple-authentication', './plugins/withTrotterShareExtension']) {
    if (!pluginNames.includes(plugin)) errors.push(`Register ${plugin} in the Expo configuration.`);
  }
  if (!fs.existsSync(path.join(root, 'plugins/withTrotterShareExtension.js'))) errors.push('The iOS share extension config plugin is missing.');
  try {
    const api = new URL(env.EXPO_PUBLIC_TROTTER_API_URL || '');
    if (api.protocol !== 'https:' || api.username || api.password || api.port || api.search || api.hash || ['localhost', '127.0.0.1'].includes(api.hostname)) throw new Error();
    if (!config.ios?.associatedDomains?.includes(`applinks:${api.hostname}`)) errors.push('Associate the invitation API host with the iOS app.');
  } catch { errors.push('Set EXPO_PUBLIC_TROTTER_API_URL to the public HTTPS API URL (without credentials, query, fragment, or a custom port).'); }
  if (simulator) notes.push('Simulator checks do not verify signing, Instagram sharing from the real app, or Apple credential state.');
  notes.push('These are configuration checks, not a native compilation or device test.');
  return { errors, notes };
}

module.exports = { checkIosReadiness };

if (require.main === module) {
  // This hook runs for Android too. Leave the existing Android build alone.
  const args = new Set(process.argv.slice(2));
  if (args.has('--eas') && process.env.EAS_BUILD_PLATFORM !== 'ios') process.exit(0);
  const root = path.resolve(__dirname, '..');
  require('@expo/env').load(root, { silent: true });
  try {
    const base = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).expo;
    const config = require('../app.config.js')({ config: base });
    const simulator = args.has('--simulator') || process.env.EAS_BUILD_PROFILE === 'iphone-simulator';
    const result = checkIosReadiness(config, process.env, { local: args.has('--local'), simulator, root });
    for (const error of result.errors) console.error(`Missing: ${error}`);
    for (const note of result.notes) console.log(note);
    if (result.errors.length) process.exitCode = 1;
    else console.log('iPhone configuration checks passed.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
