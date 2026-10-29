const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const xcode = require('xcode');
const plist = require('@expo/plist').default;
const unquote = value => String(value || '').replace(/^"|"$/g, '');

function assertIosProject(projectRoot) {
  const ios = path.join(projectRoot, 'ios');
  const xcodeName = fs.readdirSync(ios).find(name => name.endsWith('.xcodeproj'));
  assert.ok(xcodeName, 'Expo must produce an Xcode project');
  const project = xcode.project(path.join(ios, xcodeName, 'project.pbxproj')).parseSync();
  const objects = project.hash.project.objects;
  const targets = Object.entries(objects.PBXNativeTarget).filter(([, target]) => target?.isa === 'PBXNativeTarget');
  const app = targets.find(([, target]) => unquote(target.productType) === 'com.apple.product-type.application');
  const extensions = targets.filter(([, target]) => unquote(target.name) === 'TrotterShare');
  assert.ok(app, 'One app target is required');
  assert.equal(extensions.length, 1, 'Prebuild must never duplicate the share extension');
  const appName = unquote(app[1].name);
  const appInfo = plist.parse(fs.readFileSync(path.join(ios, appName, 'Info.plist'), 'utf8'));
  assert.ok(typeof appInfo.NSLocationWhenInUseUsageDescription === 'string' && appInfo.NSLocationWhenInUseUsageDescription.trim(),
    'The generated app must include NSLocationWhenInUseUsageDescription for the linked map SDK');
  const appEntitlements = plist.parse(fs.readFileSync(path.join(ios, appName, `${appName}.entitlements`), 'utf8'));
  const shareEntitlements = plist.parse(fs.readFileSync(path.join(ios, 'TrotterShare/TrotterShare.entitlements'), 'utf8'));
  assert.deepEqual(appEntitlements['com.apple.developer.applesignin'], ['Default']);
  for (const name of ['com.apple.security.application-groups', 'keychain-access-groups']) {
    assert.equal(appEntitlements[name].length, 1);
    assert.deepEqual(appEntitlements[name], shareEntitlements[name]);
  }
  assert.ok(appEntitlements['com.apple.developer.associated-domains']?.length, 'Invitation domain is required');
  const extensionInfo = plist.parse(fs.readFileSync(path.join(ios, 'TrotterShare/Info.plist'), 'utf8'));
  assert.equal(extensionInfo.NSExtension.NSExtensionPointIdentifier, 'com.apple.share-services');
  assert.equal(extensionInfo.NSExtension.NSExtensionAttributes.NSExtensionActivationRule.NSExtensionActivationSupportsWebURLWithMaxCount, 1);
  assert.equal(extensionInfo.UIAppFonts.length, 3);
  for (const font of extensionInfo.UIAppFonts) assert.ok(fs.statSync(path.join(ios, 'TrotterShare', font)).size > 0);
  const shareTarget = extensions[0][1];
  for (const phaseRef of shareTarget.buildPhases) {
    const phase = objects.PBXSourcesBuildPhase?.[phaseRef.value] || objects.PBXResourcesBuildPhase?.[phaseRef.value];
    if (!phase) continue;
    assert.equal(new Set(phase.files.map(file => file.value)).size, phase.files.length, 'No duplicate build resources');
  }
  const copyPhases = Object.values(objects.PBXCopyFilesBuildPhase || {}).filter(phase => phase?.isa === 'PBXCopyFilesBuildPhase');
  assert.ok(copyPhases.some(phase => String(phase.dstSubfolderSpec) === '13' && phase.files.some(file => String(file.comment).includes('TrotterShare.appex'))), 'The extension must be embedded in the app');
  const podfile = fs.readFileSync(path.join(ios, 'Podfile'), 'utf8');
  assert.equal((podfile.match(/pod 'react-native-google-maps'/g) || []).length, 1, 'Google Maps native pod must be installed exactly once');
  const delegate = fs.readFileSync(path.join(ios, appName, 'AppDelegate.swift'), 'utf8');
  assert.equal((delegate.match(/GMSServices.provideAPIKey/g) || []).length, 1);
  assert.equal((delegate.match(/\/\/ Trotter background share uploads/g) || []).length, 1);
  assert.match(delegate, /RCTLinkingManager.application\(application, continue: userActivity/);
  console.log('Generated Xcode project: extension embedding, shared entitlements, Apple login, invitation links, fonts, location purpose and Google Maps integration passed.');
}

module.exports = { assertIosProject };
if (require.main === module) assertIosProject(path.resolve(process.argv[2] || '.'));
