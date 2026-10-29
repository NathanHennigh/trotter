const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const test = require('node:test');
const plist = require('@expo/plist').default;
const xcode = require('xcode');
const plugin = require('../plugins/withTrotterShareExtension');
const { settings, patchAppDelegate, writeSources, configureProject } = plugin._test;
const root = path.resolve(__dirname, '..');
const config = { name: 'Trotter', version: '0.1.2', ios: { bundleIdentifier: 'com.trotter.mobilev2', supportsTablet: false, buildNumber: '3' } };

function fixture() {
  // A real parsed Xcode project exercises node-xcode's build phase/file APIs.
  const project = xcode.project(path.join(root, 'node_modules/@react-native-async-storage/async-storage/ios/RNCAsyncStorage.xcodeproj/project.pbxproj'));
  project.parseSync();
  return project;
}

test('iOS extension declares exact App Group and device keychain sharing without replacing other EAS extensions', () => {
  const result = plugin({ ...config, extra: { eas: { projectId: 'existing-project', build: { experimental: { ios: { appExtensions: [{ targetName: 'Other', bundleIdentifier: 'com.example.Other' }] } } } } } });
  assert.equal(result.extra.eas.projectId, 'existing-project');
  const extensions = result.extra.eas.build.experimental.ios.appExtensions;
  assert.equal(extensions.length, 2);
  assert.deepEqual(extensions[1], { targetName: 'TrotterShare', bundleIdentifier: 'com.trotter.mobilev2.ShareExtension', entitlements: {
    'com.apple.security.application-groups': ['group.com.trotter.mobilev2.dreamshare'],
    'keychain-access-groups': ['$(AppIdentifierPrefix)com.trotter.mobilev2.dreamshare'],
  } });
  assert.equal(plugin(result).extra.eas.build.experimental.ios.appExtensions.length, 2);
  assert.throws(() => settings(config, { appGroup: 'unscoped' }));
  assert.throws(() => settings(config, { extensionBundleIdentifier: 'com.unrelated.share' }));
});

test('prebuild adds one embedded extension with isolated build sources and repeatable resource registration', () => {
  const project = fixture();
  const values = settings(config);
  configureProject(project, config, values);
  const before = project.writeSync();
  configureProject(project, config, values);
  assert.equal(project.writeSync(), before, 'second prebuild must not duplicate targets, build phases, files, or resources');
  const nativeTargets = project.pbxNativeTargetSection();
  const target = Object.entries(nativeTargets).find(([, value]) => value?.name === '"TrotterShare"');
  assert.ok(target);
  assert.equal(target[1].productType, '"com.apple.product-type.app-extension"');
  const sources = project.pbxSourcesBuildPhaseObj(target[0]);
  assert.equal(sources.files.length, 5);
  const resources = project.pbxResourcesBuildPhaseObj(target[0]);
  assert.equal(resources.files.length, 4);
  const buildConfigs = project.pbxXCConfigurationList()[target[1].buildConfigurationList].buildConfigurations;
  for (const ref of buildConfigs) {
    const value = project.pbxXCBuildConfigurationSection()[ref.value].buildSettings;
    assert.equal(value.APPLICATION_EXTENSION_API_ONLY, 'YES');
    assert.equal(value.CODE_SIGN_ENTITLEMENTS, '"TrotterShare/TrotterShare.entitlements"');
    assert.equal(value.TARGETED_DEVICE_FAMILY, '1');
    assert.equal(value.SWIFT_VERSION, '5.0');
    assert.equal(value.MARKETING_VERSION, config.version);
    assert.equal(value.CURRENT_PROJECT_VERSION, config.ios.buildNumber);
  }
  assert.match(before, /TrotterShare.appex in Copy Files/);
});

test('generated files share the same store in both targets and do not include React in the extension', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'trotter-ios-share-'));
  try {
    writeSources(root, folder, config, settings(config));
    const extension = plist.parse(fs.readFileSync(path.join(folder, 'TrotterShare/Info.plist'), 'utf8'));
    assert.equal(extension.TrotterShareKeychainGroup, '$(AppIdentifierPrefix)com.trotter.mobilev2.dreamshare');
    assert.equal(extension.NSExtension.NSExtensionPrincipalClass, '$(PRODUCT_MODULE_NAME).ShareViewController');
    assert.deepEqual({ ...extension.NSExtension.NSExtensionAttributes.NSExtensionActivationRule }, {
      NSExtensionActivationSupportsWebURLWithMaxCount: 1, NSExtensionActivationSupportsText: true,
    });
    for (const name of ['DreamShareInbox.swift', 'DreamShareStore.swift', 'DreamShareUploader.swift', 'TrotterShareConfiguration.swift']) {
      assert.equal(fs.readFileSync(path.join(folder, 'TrotterShare', name), 'utf8'), fs.readFileSync(path.join(folder, 'TrotterDreamShare', name), 'utf8'));
    }
    assert.equal(fs.existsSync(path.join(folder, 'TrotterShare/TrotterDreamShare.m')), false);
    assert.ok(fs.statSync(path.join(folder, 'TrotterShare/Newsreader-Regular.ttf')).size > 1000);
  } finally {
    assert.equal(path.dirname(path.resolve(folder)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(folder).startsWith('trotter-ios-share-'));
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('serialized native source and resource paths resolve to the generated files', () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'trotter-ios-share-'));
  try {
    writeSources(root, folder, config, settings(config));
    const project = fixture();
    configureProject(project, config, settings(config));
    const projectFile = path.join(folder, 'project.pbxproj');
    fs.writeFileSync(projectFile, project.writeSync());
    const parsed = xcode.project(projectFile).parseSync();
    const unquote = value => String(value || '').replace(/^"|"$/g, '');
    for (const group of Object.values(parsed.hash.project.objects.PBXGroup)) {
      if (!['TrotterDreamShare', 'TrotterShare'].includes(unquote(group?.name))) continue;
      for (const child of group.children) {
        const file = parsed.pbxFileReferenceSection()[child.value];
        const resolved = path.join(folder, unquote(group.path), unquote(file.path));
        assert.ok(fs.existsSync(resolved), `Xcode must resolve the generated file: ${resolved}`);
      }
    }
  } finally {
    assert.equal(path.dirname(path.resolve(folder)), path.resolve(os.tmpdir()));
    assert.ok(path.basename(folder).startsWith('trotter-ios-share-'));
    fs.rmSync(folder, { recursive: true, force: true });
  }
});

test('AppDelegate dispatches background transfer events to Trotter and forwards unrelated sessions to Expo', () => {
  const source = 'import Expo\npublic class AppDelegate: ExpoAppDelegate {\n}\n';
  const result = patchAppDelegate(source);
  assert.equal(patchAppDelegate(result), result);
  assert.match(result, /if !DreamShareUploader.shared.handleBackgroundEvents/);
  assert.match(result, /super.application\(application, handleEventsForBackgroundURLSession/);
  assert.throws(() => patchAppDelegate('class AppDelegate: ExpoAppDelegate { func handleEventsForBackgroundURLSession() {} }'), /Merge/);
});
