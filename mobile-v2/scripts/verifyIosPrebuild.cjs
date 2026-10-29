// Generate an isolated Xcode project, preserving the customized Android tree.
// This validates Expo/plugin generation. Only Xcode on macOS can compile it.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
if (process.platform === 'win32') {
  console.error('Expo generates iOS projects on macOS/Linux. Run this check on your Mac or a WSL checkout with Linux npm dependencies.');
  process.exit(1);
}
const scratch = path.join(root, '.cache', `ios-prebuild-${Date.now()}`);
fs.mkdirSync(scratch, { recursive: true });
for (const file of ['package.json', 'package-lock.json', 'app.json', 'app.config.js', 'App.tsx', 'babel.config.js', 'tsconfig.json']) {
  fs.copyFileSync(path.join(root, file), path.join(scratch, file));
}
for (const folder of ['plugins', 'native-ios', 'assets/world-window/fonts']) {
  fs.cpSync(path.join(root, folder), path.join(scratch, folder), { recursive: true });
}
fs.copyFileSync(path.join(root, 'assets/world-window/app-icon.png'), path.join(scratch, 'assets/world-window/app-icon.png'));
fs.symlinkSync(path.join(root, 'node_modules'), path.join(scratch, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
const result = spawnSync(process.execPath, [require.resolve('expo/bin/cli'), 'prebuild', '--platform', 'ios', '--no-install'], {
  cwd: scratch,
  env: { ...process.env, CI: '1', EXPO_NO_DOTENV: '1',
    EAS_PROJECT_ID: '', APPLE_TEAM_ID: 'TESTTEAM01',
    EXPO_PUBLIC_TROTTER_API_URL: 'https://api.prebuild-test.invalid',
    GOOGLE_MAPS_IOS_API_KEY: 'prebuild-test-ios-key', GOOGLE_MAPS_ANDROID_API_KEY: '',
  },
  stdio: 'inherit',
});
console.log(`Generated-project fixture: ${scratch}`);
if (result.error) console.error(result.error.message);
if (result.status === 0) require('./assertIosProject.cjs').assertIosProject(scratch);
process.exitCode = result.status ?? 1;
