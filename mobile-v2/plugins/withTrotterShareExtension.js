const fs = require('node:fs');
const path = require('node:path');
const plist = require('@expo/plist').default;
const { withEntitlementsPlist, withInfoPlist, withXcodeProject, withAppDelegate } = require('@expo/config-plugins');

const TARGET = 'TrotterShare';
const APP_SOURCES = 'TrotterDreamShare';
const sharedFiles = ['DreamShareInbox.swift', 'DreamShareStore.swift', 'DreamShareUploader.swift'];
const fonts = ['Newsreader-Regular.ttf', 'DMSans-Regular.ttf', 'DMSans-SemiBold.ttf'];
const unquote = value => String(value || '').replace(/^"|"$/g, '');
const unique = list => [...new Set(list)];

function settings(config, options = {}) {
  const bundleIdentifier = config.ios?.bundleIdentifier;
  if (!bundleIdentifier || !/^[A-Za-z0-9.-]+$/.test(bundleIdentifier)) throw new Error('Trotter sharing needs a valid ios.bundleIdentifier.');
  const appGroup = options.appGroup || `group.${bundleIdentifier}.dreamshare`;
  const extensionBundleIdentifier = options.extensionBundleIdentifier || `${bundleIdentifier}.ShareExtension`;
  if (!/^group\.[A-Za-z0-9.-]+$/.test(appGroup) || !extensionBundleIdentifier.startsWith(`${bundleIdentifier}.`) || !/^[A-Za-z0-9.-]+$/.test(extensionBundleIdentifier)) {
    throw new Error('Invalid Trotter Share App Group or extension bundle identifier.');
  }
  return { bundleIdentifier, appGroup, extensionBundleIdentifier,
    keychainGroup: `$(AppIdentifierPrefix)${bundleIdentifier}.dreamshare` };
}

function configurationSource(values) {
  return `import Foundation
enum TrotterShareConfiguration {
  static let appGroup = "${values.appGroup}"
  static let bundleIdentifier = "${values.bundleIdentifier}"
  static var keychainGroup: String {
    // Xcode expands the team prefix in Info.plist for both signed targets.
    Bundle.main.object(forInfoDictionaryKey: "TrotterShareKeychainGroup") as? String ?? ""
  }
}
`;
}

function writeSources(root, nativeRoot, config, values) {
  for (const destination of [APP_SOURCES, TARGET]) {
    const folder = path.join(nativeRoot, destination);
    fs.mkdirSync(folder, { recursive: true });
    for (const file of sharedFiles) fs.copyFileSync(path.join(root, 'native-ios/shared', file), path.join(folder, file));
    fs.writeFileSync(path.join(folder, 'TrotterShareConfiguration.swift'), configurationSource(values));
  }
  for (const file of ['TrotterDreamShare.swift', 'TrotterDreamShare.m']) {
    fs.copyFileSync(path.join(root, 'native-ios/bridge', file), path.join(nativeRoot, APP_SOURCES, file));
  }
  fs.copyFileSync(path.join(root, 'native-ios/extension/ShareViewController.swift'), path.join(nativeRoot, TARGET, 'ShareViewController.swift'));
  for (const file of fonts) fs.copyFileSync(path.join(root, 'assets/world-window/fonts', file), path.join(nativeRoot, TARGET, file));
  const info = {
    CFBundleDisplayName: 'Trotter', CFBundleName: '$(PRODUCT_NAME)', CFBundleIdentifier: '$(PRODUCT_BUNDLE_IDENTIFIER)',
    CFBundleExecutable: '$(EXECUTABLE_NAME)', CFBundlePackageType: 'XPC!', CFBundleInfoDictionaryVersion: '6.0',
    CFBundleShortVersionString: '$(MARKETING_VERSION)', CFBundleVersion: '$(CURRENT_PROJECT_VERSION)',
    TrotterShareKeychainGroup: values.keychainGroup, UIAppFonts: fonts,
    NSExtension: { NSExtensionPointIdentifier: 'com.apple.share-services',
      NSExtensionPrincipalClass: '$(PRODUCT_MODULE_NAME).ShareViewController',
      NSExtensionAttributes: { NSExtensionActivationRule: {
        NSExtensionActivationSupportsWebURLWithMaxCount: 1, NSExtensionActivationSupportsText: true,
      } } },
  };
  fs.writeFileSync(path.join(nativeRoot, TARGET, 'Info.plist'), plist.build(info));
  fs.writeFileSync(path.join(nativeRoot, TARGET, `${TARGET}.entitlements`), plist.build({
    'com.apple.security.application-groups': [values.appGroup], 'keychain-access-groups': [values.keychainGroup],
  }));
  fs.writeFileSync(path.join(nativeRoot, TARGET, 'PrivacyInfo.xcprivacy'), plist.build({
    NSPrivacyTracking: false, NSPrivacyTrackingDomains: [], NSPrivacyCollectedDataTypes: [], NSPrivacyAccessedAPITypes: [],
  }));
}

function targetConfigurations(project, target) {
  const lists = project.pbxXCConfigurationList();
  const list = lists[target.buildConfigurationList];
  return (list?.buildConfigurations || []).map(ref => project.pbxXCBuildConfigurationSection()[ref.value]);
}

function addSources(project, targetId, folder, names) {
  const groups = project.hash.project.objects.PBXGroup;
  let groupId = Object.keys(groups).find(key => groups[key]?.isa === 'PBXGroup' && unquote(groups[key].name) === folder);
  if (!groupId) {
    groupId = project.addPbxGroup([], folder, undefined).uuid;
    groups[project.getFirstProject().firstProject.mainGroup].children.push({ value: groupId, comment: folder });
  }
  // node-xcode serializes an undefined path as the literal folder "undefined".
  // These files already carry their project-relative folder in their path.
  delete groups[groupId].path;
  for (const name of names) {
    const file = `${folder}/${name}`;
    if (!project.hasFile(file)) project.addSourceFile(file, { target: targetId }, groupId);
  }
  return groupId;
}

function configureProject(project, config, values) {
  const app = project.getFirstTarget();
  const objects = project.hash.project.objects;
  for (const section of ['PBXTargetDependency', 'PBXContainerItemProxy']) objects[section] ||= {};
  let entry = Object.entries(project.pbxNativeTargetSection()).find(([, value]) => value?.isa === 'PBXNativeTarget' && unquote(value.name) === TARGET);
  let extension;
  if (entry) extension = { uuid: entry[0], pbxNativeTarget: entry[1] };
  else {
    extension = project.addTarget(TARGET, 'app_extension', TARGET, values.extensionBundleIdentifier);
    project.addBuildPhase([], 'PBXSourcesBuildPhase', 'Sources', extension.uuid);
    project.addBuildPhase([], 'PBXFrameworksBuildPhase', 'Frameworks', extension.uuid);
    project.addBuildPhase([], 'PBXResourcesBuildPhase', 'Resources', extension.uuid);
  }
  const appConfigurations = targetConfigurations(project, app.firstTarget);
  for (const configuration of targetConfigurations(project, extension.pbxNativeTarget)) {
    const appSettings = appConfigurations.find(candidate => unquote(candidate.name) === unquote(configuration.name))?.buildSettings || {};
    Object.assign(configuration.buildSettings, {
      PRODUCT_BUNDLE_IDENTIFIER: `"${values.extensionBundleIdentifier}"`, PRODUCT_NAME: '"$(TARGET_NAME)"',
      PRODUCT_MODULE_NAME: TARGET, INFOPLIST_FILE: `"${TARGET}/Info.plist"`,
      CODE_SIGN_ENTITLEMENTS: `"${TARGET}/${TARGET}.entitlements"`, CODE_SIGN_STYLE: 'Automatic',
      SWIFT_VERSION: '5.0', IPHONEOS_DEPLOYMENT_TARGET: appSettings.IPHONEOS_DEPLOYMENT_TARGET || '15.1',
      TARGETED_DEVICE_FAMILY: config.ios?.supportsTablet ? '"1,2"' : '1',
      APPLICATION_EXTENSION_API_ONLY: 'YES', SKIP_INSTALL: 'YES',
      // Expo writes the app version directly into Info.plist; template build
      // settings may still say 1.0. The extension must match the Expo version.
      MARKETING_VERSION: config.version || appSettings.MARKETING_VERSION || '1.0',
      CURRENT_PROJECT_VERSION: config.ios?.buildNumber || appSettings.CURRENT_PROJECT_VERSION || '1',
      GENERATE_INFOPLIST_FILE: 'NO', CLANG_ENABLE_MODULES: 'YES',
    });
    if (config.ios?.appleTeamId || appSettings.DEVELOPMENT_TEAM) configuration.buildSettings.DEVELOPMENT_TEAM = config.ios?.appleTeamId || appSettings.DEVELOPMENT_TEAM;
  }
  addSources(project, app.uuid, APP_SOURCES, [...sharedFiles, 'TrotterShareConfiguration.swift', 'TrotterDreamShare.swift', 'TrotterDreamShare.m']);
  const extensionGroup = addSources(project, extension.uuid, TARGET, [...sharedFiles, 'TrotterShareConfiguration.swift', 'ShareViewController.swift']);
  // node-xcode's resource helper assumes this conventional group exists even
  // when the resource is registered under a different explicit group.
  if (!project.pbxGroupByName('Resources')) {
    const resourceGroup = project.addPbxGroup([], 'Resources').uuid;
    delete objects.PBXGroup[resourceGroup].path;
    objects.PBXGroup[project.getFirstProject().firstProject.mainGroup].children.push({ value: resourceGroup, comment: 'Resources' });
  }
  for (const file of [...fonts, 'PrivacyInfo.xcprivacy']) {
    const filePath = `${TARGET}/${file}`;
    if (!project.hasFile(filePath)) project.addResourceFile(filePath, { target: extension.uuid }, extensionGroup);
  }
  return project;
}

function patchAppDelegate(contents) {
  if (contents.includes('// Trotter background share uploads')) return contents;
  if (contents.includes('handleEventsForBackgroundURLSession')) throw new Error('Merge Trotter share background-session handling with the existing AppDelegate handler.');
  const declaration = /((?:public )?class AppDelegate:\s*ExpoAppDelegate\s*\{)/;
  if (!declaration.test(contents)) throw new Error('Trotter sharing expects the Expo Swift AppDelegate.');
  return contents.replace(declaration, `$1
  // Trotter background share uploads
  public override func application(
    _ application: UIApplication,
    handleEventsForBackgroundURLSession identifier: String,
    completionHandler: @escaping () -> Void
  ) {
    if !DreamShareUploader.shared.handleBackgroundEvents(identifier: identifier, completion: completionHandler) {
      super.application(application, handleEventsForBackgroundURLSession: identifier, completionHandler: completionHandler)
    }
  }
`);
}

function withTrotterShareExtension(config, options = {}) {
  const values = settings(config, options);
  const entitlements = { 'com.apple.security.application-groups': [values.appGroup], 'keychain-access-groups': [values.keychainGroup] };
  config = withEntitlementsPlist(config, mod => {
    for (const [key, list] of Object.entries(entitlements)) mod.modResults[key] = unique([...(mod.modResults[key] || []), ...list]);
    return mod;
  });
  config = withInfoPlist(config, mod => { mod.modResults.TrotterShareKeychainGroup = values.keychainGroup; return mod; });
  config = withAppDelegate(config, mod => {
    if (mod.modResults.language !== 'swift') throw new Error('Trotter sharing requires a Swift AppDelegate.');
    mod.modResults.contents = patchAppDelegate(mod.modResults.contents); return mod;
  });
  config = withXcodeProject(config, mod => {
    writeSources(mod.modRequest.projectRoot, mod.modRequest.platformProjectRoot, mod, values);
    mod.modResults = configureProject(mod.modResults, mod, values); return mod;
  });
  config.extra ||= {}; config.extra.eas ||= {}; config.extra.eas.build ||= {};
  config.extra.eas.build.experimental ||= {}; config.extra.eas.build.experimental.ios ||= {};
  const ios = config.extra.eas.build.experimental.ios;
  ios.appExtensions = [...(ios.appExtensions || []).filter(item => item.targetName !== TARGET), {
    targetName: TARGET, bundleIdentifier: values.extensionBundleIdentifier, entitlements,
  }];
  return config;
}

module.exports = withTrotterShareExtension;
module.exports._test = { settings, patchAppDelegate, writeSources, configureProject };
