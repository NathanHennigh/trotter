const fs = require('node:fs');
const path = require('node:path');

// The same ignored file is read by Gradle, including in the WSL build copy.
// These are app-restricted Maps SDK keys. The Places server key never belongs here.
function mapsKeys() {
  const file = path.join(__dirname, 'android', 'google-maps.properties');
  const values = {};
  if (fs.existsSync(file)) {
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const match = line.match(/^\s*(androidApiKey|iosApiKey)\s*=\s*(\S+)\s*$/);
      if (match) values[match[1]] = match[2];
    }
  }
  return {
    android: (process.env.GOOGLE_MAPS_ANDROID_API_KEY || values.androidApiKey || '').trim(),
    ios: (process.env.GOOGLE_MAPS_IOS_API_KEY || values.iosApiKey || '').trim(),
  };
}

module.exports = ({ config }) => {
  const keys = mapsKeys();
  const projectId = (process.env.EAS_PROJECT_ID || config.extra?.eas?.projectId || '').trim();
  const teamId = (process.env.APPLE_TEAM_ID || config.ios?.appleTeamId || '').trim();
  if (projectId && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(projectId)) {
    throw new Error('EAS_PROJECT_ID must be the UUID of the actual linked Expo project.');
  }
  if (teamId && !/^[A-Z0-9]{10}$/.test(teamId)) throw new Error('APPLE_TEAM_ID must be a 10-character Apple Developer team identifier.');
  // Universal links are associated only with the API host that issues invitations.
  // The bearer invitation stays in the fragment and is never sent to AASA/CDN.
  let invitationDomain;
  try {
    const api = new URL(process.env.EXPO_PUBLIC_TROTTER_API_URL || '');
    if (api.protocol === 'https:' && !api.username && !api.password && !api.port && !api.search && !api.hash) invitationDomain = `applinks:${api.hostname}`;
  } catch { /* The preflight explains missing/invalid release configuration. */ }
  return {
    ...config,
    android: {
      ...config.android,
      ...(keys.android ? { config: { ...config.android?.config, googleMaps: { apiKey: keys.android } } } : {}),
    },
    ios: {
      ...config.ios,
      ...(teamId ? { appleTeamId: teamId } : {}),
      associatedDomains: [...new Set([...(config.ios?.associatedDomains || []), ...(invitationDomain ? [invitationDomain] : [])])],
      ...(keys.ios ? { config: { ...config.ios?.config, googleMapsApiKey: keys.ios } } : {}),
    },
    extra: {
      ...config.extra,
      ...(projectId ? { eas: { ...config.extra?.eas, projectId } } : {}),
      googleMapsAndroidConfigured: Boolean(keys.android),
      googleMapsIosConfigured: Boolean(keys.ios),
      // Enable only after Trotter's own Apple setup and end-to-end verification.
      appleSignInEnabled: Boolean(teamId && process.env.EXPO_PUBLIC_APPLE_SIGN_IN_ENABLED === 'true'),
    },
  };
};
