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
  return {
    ...config,
    android: {
      ...config.android,
      ...(keys.android ? { config: { ...config.android?.config, googleMaps: { apiKey: keys.android } } } : {}),
    },
    ios: {
      ...config.ios,
      ...(keys.ios ? { config: { ...config.ios?.config, googleMapsApiKey: keys.ios } } : {}),
    },
    extra: {
      ...config.extra,
      googleMapsAndroidConfigured: Boolean(keys.android),
      googleMapsIosConfigured: Boolean(keys.ios),
    },
  };
};
