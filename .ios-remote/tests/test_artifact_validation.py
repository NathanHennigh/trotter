import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import plistlib
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('artifacts', Path(__file__).parents[1] / 'mac' / 'artifact-validation.py')
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


def simulator_binary(entitlements):
    payload = plistlib.dumps(entitlements)
    segment = bytearray(152)
    struct.pack_into('<II', segment, 0, 0x19, len(segment))
    segment[8:24] = b'__TEXT'.ljust(16, b'\0')
    struct.pack_into('<I', segment, 64, 1)
    segment[72:88] = b'__entitlements'.ljust(16, b'\0')
    segment[88:104] = b'__TEXT'.ljust(16, b'\0')
    struct.pack_into('<QI', segment, 112, len(payload), 32 + len(segment))
    return struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 1, len(segment), 0, 0) + segment + payload


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='trotter-artifact-test-')
        self.root = Path(self.temp.name)
        self.destination = self.root / 'extracted'
        self.destination.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def make_zip(self, files):
        archive = self.root / 'app.ipa'
        with zipfile.ZipFile(archive, 'w') as output:
            for name, data in files:
                output.writestr(name, data)
        return archive

    def test_zip_extracts_only_inside_new_directory(self):
        archive = self.make_zip([('Payload/Trotter.app/main.jsbundle', b'code')])
        artifact.extract_archive(archive, self.destination, 'zip')
        self.assertEqual((self.destination / 'Payload/Trotter.app/main.jsbundle').read_bytes(), b'code')
        with self.assertRaisesRegex(ValueError, 'new empty'):
            artifact.extract_archive(archive, self.destination, 'zip')

    def test_zip_path_traversal_and_windows_paths_are_rejected(self):
        for name in ('../outside', '/outside', 'C:/outside', r'Payload\..\outside'):
            with self.subTest(name=name):
                archive = self.make_zip([(name, b'bad')])
                with self.assertRaises(ValueError):
                    artifact.extract_archive(archive, self.destination, 'zip')
                self.assertFalse((self.root / 'outside').exists())

    def test_duplicate_members_are_rejected(self):
        archive = self.make_zip([('same', b'one'), ('same', b'two')])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            artifact.extract_archive(archive, self.destination, 'zip')

    def test_zip_link_cannot_escape(self):
        item = zipfile.ZipInfo('Payload/Trotter.app/link')
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.make_zip([(item, b'../../../outside')])
        with self.assertRaisesRegex(ValueError, 'escapes'):
            artifact.extract_archive(archive, self.destination, 'zip')

    def test_tar_special_files_are_rejected(self):
        archive = self.root / 'app.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            item = tarfile.TarInfo('device')
            item.type = tarfile.CHRTYPE
            output.addfile(item)
        with self.assertRaisesRegex(ValueError, 'special file'):
            artifact.extract_archive(archive, self.destination, 'tar')

    def test_tar_content_cannot_be_written_through_link(self):
        archive = self.root / 'app.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            link = tarfile.TarInfo('alias'); link.type = tarfile.SYMTYPE; link.linkname = 'actual'
            output.addfile(link)
            item = tarfile.TarInfo('alias/file'); item.size = 3
            output.addfile(item, io.BytesIO(b'bad'))
        with self.assertRaisesRegex(ValueError, 'writes through'):
            artifact.extract_archive(archive, self.destination, 'tar')

    def test_tar_leading_dot_and_executable_mode_are_supported(self):
        archive = self.root / 'app.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            top = tarfile.TarInfo('.'); top.type = tarfile.DIRTYPE; output.addfile(top)
            item = tarfile.TarInfo('./Trotter.app/Trotter'); item.mode = 0o755; item.size = 3
            output.addfile(item, io.BytesIO(b'app'))
        artifact.extract_archive(archive, self.destination, 'tar')
        self.assertEqual((self.destination / 'Trotter.app/Trotter').read_bytes(), b'app')


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='trotter-bundle-test-')
        self.app = Path(self.temp.name) / 'Trotter.app'
        self.extension = self.app / 'PlugIns' / 'TrotterShare.appex'
        self.extension.mkdir(parents=True)
        self.info = {'CFBundleIdentifier': artifact.BUNDLE, 'CFBundleShortVersionString': '0.1.2', 'CFBundleVersion': '3',
                     'CFBundleSupportedPlatforms': ['iPhoneSimulator'], 'CFBundlePackageType': 'APPL', 'CFBundleExecutable': 'Trotter'}
        self.ext_info = dict(self.info, CFBundleIdentifier=artifact.EXTENSION, CFBundleExecutable='TrotterShare',
                             NSExtension={'NSExtensionPointIdentifier': 'com.apple.share-services'})
        (self.app / 'Trotter').write_bytes(b'app'); (self.extension / 'TrotterShare').write_bytes(b'extension')
        self.write()

    def tearDown(self): self.temp.cleanup()

    def write(self):
        (self.app / 'Info.plist').write_bytes(plistlib.dumps(self.info, fmt=plistlib.FMT_BINARY))
        (self.extension / 'Info.plist').write_bytes(plistlib.dumps(self.ext_info))

    def test_matching_trotter_simulator_bundle(self):
        value = artifact.validate_bundle(self.app, 'iPhoneSimulator')
        self.assertEqual(value['bundle_id'], artifact.BUNDLE)
        self.assertEqual(value['build'], '3')

    def test_wrong_app_is_rejected_before_install(self):
        self.info['CFBundleIdentifier'] = 'com.etchtheword.app'; self.write()
        with self.assertRaisesRegex(ValueError, 'not the Trotter'):
            artifact.validate_bundle(self.app, 'iPhoneSimulator')

    def test_extension_and_build_must_match(self):
        for key, value in [('CFBundleIdentifier', 'com.other.Share'), ('CFBundleVersion', '4')]:
            original = self.ext_info[key]; self.ext_info[key] = value; self.write()
            with self.assertRaises(ValueError): artifact.validate_bundle(self.app, 'iPhoneSimulator')
            self.ext_info[key] = original

    def test_device_artifact_is_not_installed_as_simulator(self):
        self.info['CFBundleSupportedPlatforms'] = ['iPhoneOS']; self.write()
        with self.assertRaisesRegex(ValueError, 'platform'):
            artifact.validate_bundle(self.app, 'iPhoneSimulator')

    def prepare_simulator_entitlements(self):
        keychain = 'FAKETEAMID.' + artifact.BUNDLE + '.dreamshare'
        self.info['TrotterShareKeychainGroup'] = keychain
        self.ext_info['TrotterShareKeychainGroup'] = keychain
        self.write()
        for target, bundle, executable in [(self.app, artifact.BUNDLE, 'Trotter'), (self.extension, artifact.EXTENSION, 'TrotterShare')]:
            (target / executable).write_bytes(simulator_binary({
                'application-identifier': 'FAKETEAMID.' + bundle,
                'keychain-access-groups': [keychain],
                'com.apple.security.application-groups': [artifact.GROUP],
            }))

    def test_simulator_injected_entitlements_match_both_targets(self):
        self.prepare_simulator_entitlements()
        artifact.validate_simulator_entitlements(self.app)

    def test_missing_simulator_entitlements_are_rejected_before_install(self):
        self.prepare_simulator_entitlements()
        (self.app / 'Trotter').write_bytes(struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 0, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, 'entitlements are missing'):
            artifact.validate_simulator_entitlements(self.app)

    def test_simulator_keychain_and_app_group_must_be_usable(self):
        for key in ['application-identifier', 'keychain-access-groups', 'com.apple.security.application-groups']:
            with self.subTest(key=key):
                self.prepare_simulator_entitlements()
                executable = self.extension / 'TrotterShare'
                values = artifact.simulator_entitlements(executable)
                del values[key]
                executable.write_bytes(simulator_binary(values))
                with self.assertRaises(ValueError): artifact.validate_simulator_entitlements(self.app)
        self.prepare_simulator_entitlements()
        self.ext_info['TrotterShareKeychainGroup'] = 'WRONG.' + artifact.BUNDLE + '.dreamshare'; self.write()
        with self.assertRaisesRegex(ValueError, 'Keychain'):
            artifact.validate_simulator_entitlements(self.app)

    def test_macho_entitlement_offsets_are_bounded(self):
        self.prepare_simulator_entitlements()
        executable = self.app / 'Trotter'
        data = bytearray(executable.read_bytes())
        struct.pack_into('<I', data, 32 + 72 + 48, len(data) + 1)
        executable.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'bounds'):
            artifact.simulator_entitlements(executable)


class SigningTests(unittest.TestCase):
    def setUp(self):
        self.team = 'TESTTEAM01'; self.prefix = 'APPPRFX001'
        self.expected = {'team_id': self.team, 'app_id_prefix': self.prefix, 'api_url': 'https://api.example.invalid'}
        self.info = {'CFBundleIdentifier': artifact.BUNDLE, 'TrotterShareKeychainGroup': self.prefix + '.' + artifact.BUNDLE + '.dreamshare'}
        self.signed = {'application-identifier': self.prefix + '.' + artifact.BUNDLE,
                       'com.apple.developer.team-identifier': self.team, 'get-task-allow': False,
                       'com.apple.security.application-groups': [artifact.GROUP],
                       'keychain-access-groups': [self.info['TrotterShareKeychainGroup']],
                       'com.apple.developer.applesignin': ['Default'],
                       'com.apple.developer.associated-domains': ['applinks:api.example.invalid']}
        self.profile = {'TeamIdentifier': [self.team], 'ApplicationIdentifierPrefix': [self.prefix],
                        'ExpirationDate': datetime.now(timezone.utc) + timedelta(days=10),
                        'DeveloperCertificates': [b'actual-leaf'], 'Entitlements': copy.deepcopy(self.signed)}
        self.profile['Entitlements']['keychain-access-groups'] = [self.prefix + '.*']
        self.profile['Entitlements']['com.apple.developer.associated-domains'] = ['*']

    def verify(self, **kwargs):
        artifact.validate_signed_target(self.info, self.signed, self.profile, b'actual-leaf', self.expected, **kwargs)

    def test_signed_app_and_different_valid_app_id_prefix(self): self.verify()

    def test_expired_debug_device_profiles_are_rejected(self):
        cases = [('ExpirationDate', datetime.now(timezone.utc) - timedelta(days=1)), ('ProvisionedDevices', ['phone']), ('ProvisionsAllDevices', True)]
        for key, value in cases:
            with self.subTest(key=key):
                original = copy.deepcopy(self.profile); self.profile[key] = value
                with self.assertRaises(ValueError): self.verify()
                self.profile = original
        self.signed['get-task-allow'] = True
        with self.assertRaises(ValueError): self.verify()

    def test_signed_leaf_must_be_in_profile(self):
        self.profile['DeveloperCertificates'] = [b'other-leaf']
        with self.assertRaisesRegex(ValueError, 'certificate'): self.verify()

    def test_profile_must_allow_every_signed_keychain_group(self):
        self.signed['keychain-access-groups'].append(self.signed['application-identifier'])
        self.profile['Entitlements']['keychain-access-groups'] = [self.info['TrotterShareKeychainGroup']]
        with self.assertRaisesRegex(ValueError, 'Keychain'): self.verify()

    def test_foreign_team_group_keychain_or_invite_domain_are_rejected(self):
        cases = [('com.apple.developer.team-identifier', 'OTHERTEAM1'),
                 ('com.apple.security.application-groups', ['group.com.etchtheword.app']),
                 ('keychain-access-groups', [self.info['TrotterShareKeychainGroup'], self.prefix + '.com.etchtheword.app']),
                 ('com.apple.developer.associated-domains', ['applinks:etch.example.invalid'])]
        for key, value in cases:
            with self.subTest(key=key):
                original = copy.deepcopy(self.signed); self.signed[key] = value
                with self.assertRaises(ValueError): self.verify()
                self.signed = original

    def test_share_extension_has_own_profile_without_parent_capabilities(self):
        self.info['CFBundleIdentifier'] = artifact.EXTENSION
        for grant in (self.signed, self.profile['Entitlements']):
            grant['application-identifier'] = self.prefix + '.' + artifact.EXTENSION
            grant.pop('com.apple.developer.applesignin'); grant.pop('com.apple.developer.associated-domains')
        self.verify(extension=True)
        self.signed['com.apple.developer.applesignin'] = ['Default']
        with self.assertRaises(ValueError): self.verify(extension=True)


if __name__ == '__main__': unittest.main()
