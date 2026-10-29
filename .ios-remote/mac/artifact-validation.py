#!/usr/bin/env python3
"""Read-only Trotter artifact checks shared by the Mac release and smoke helpers.

Archive extraction is explicit and bounded, including link validation, so neither
helper can write outside its newly-created extraction directory.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import struct
import sys
import tarfile
from urllib.parse import urlsplit
import zipfile

BUNDLE = "com.trotter.mobilev2"
EXTENSION = BUNDLE + ".ShareExtension"
GROUP = "group." + BUNDLE + ".dreamshare"
MAX_FILES = 30000
MAX_BYTES = 4 * 1024 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_name(name):
    require(isinstance(name, str) and name and "\\" not in name and "\x00" not in name,
            "Unsafe archive member name")
    value = PurePosixPath(name)
    require(not value.is_absolute() and ".." not in value.parts
            and not re.match(r"^[A-Za-z]:", name), "Archive member escapes its directory")
    return value


def within(root, path):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, RuntimeError):
        return False


def extract_archive(archive, destination, kind):
    root = Path(destination)
    require(root.is_dir() and not root.is_symlink() and not any(root.iterdir()),
            "Extraction requires a new empty directory")
    links = []
    seen = set()
    total = 0
    source = zipfile.ZipFile(archive) if kind == "zip" else tarfile.open(archive, "r:gz")
    with source:
        entries = source.infolist() if kind == "zip" else source.getmembers()
        require(len(entries) <= MAX_FILES, "Archive contains too many members")
        for member in entries:
            name = member.filename if kind == "zip" else member.name
            relative = safe_name(name)
            # A leading './' directory entry is common in simulator tarballs.
            if str(relative) == ".":
                continue
            canonical = str(relative)
            require(canonical not in seen, "Duplicate archive path: " + canonical)
            seen.add(canonical)
            target = root.joinpath(*relative.parts)
            require(within(root, target), "Archive member escapes its directory")
            size = member.file_size if kind == "zip" else member.size
            total += size
            require(size >= 0 and total <= MAX_BYTES, "Archive exceeds extraction size limit")
            mode = (member.external_attr >> 16) if kind == "zip" else member.mode
            directory = member.is_dir() if kind == "zip" else member.isdir()
            symbolic = stat.S_ISLNK(mode) if kind == "zip" else member.issym()
            hard = False if kind == "zip" else member.islnk()
            if directory:
                target.mkdir(parents=True, exist_ok=True)
                continue
            if symbolic or hard:
                require(size < 4096 if kind == "zip" else True, "Oversized archive link")
                link = source.read(member).decode("utf-8") if kind == "zip" else member.linkname
                require(link and not PurePosixPath(link).is_absolute() and "\\" not in link
                        and "\x00" not in link and not re.match(r"^[A-Za-z]:", link), "Unsafe archive link")
                resolved = (root if hard else target.parent).joinpath(link)
                require(within(root, resolved), "Archive link escapes its directory")
                links.append((target, link, hard))
                continue
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG) if kind == "zip" else member.isfile(),
                    "Archive contains a special file")
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = source.open(member) if kind == "zip" else source.extractfile(member)
            require(stream is not None, "Archive member cannot be read")
            with stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            os.chmod(str(target), (mode & 0o777) or 0o600)
        # No archive member may be written through a symlink supplied by that archive.
        for target, _, _ in links:
            require(not any(other != target and target in other.parents
                            for other in (root.joinpath(*PurePosixPath(name).parts) for name in seen)),
                    "Archive writes through a link")
        for target, link, hard in sorted(links, key=lambda item: not item[2]):
            target.parent.mkdir(parents=True, exist_ok=True)
            if hard:
                original = root.joinpath(link)
                require(original.is_file() and not original.is_symlink(), "Unsafe archive hard link")
                os.link(str(original), str(target))
            else:
                os.symlink(link, str(target))
        require(all(within(root, target) for target, _, _ in links), "Archive link chain escapes its directory")


def plist(path):
    with Path(path).open("rb") as source:
        return plistlib.load(source)


def find_app(root, kind):
    root = Path(root)
    if kind == "zip":
        apps = list((root / "Payload").glob("*.app"))
    else:
        apps = []
        for folder, directories, _ in os.walk(str(root), followlinks=False):
            for name in list(directories):
                if name.endswith(".app"):
                    apps.append(Path(folder) / name)
                    directories.remove(name)
    require(len(apps) == 1 and apps[0].is_dir() and not apps[0].is_symlink(), "Expected exactly one app bundle")
    return apps[0]


def validate_bundle(app, platform):
    app = Path(app)
    info = plist(app / "Info.plist")
    require(info.get("CFBundleIdentifier") == BUNDLE, "Artifact is not the Trotter app")
    require(info.get("CFBundleSupportedPlatforms") == [platform], "Artifact platform does not match this action")
    require(info.get("CFBundlePackageType") == "APPL", "Artifact is not an application")
    version, build = info.get("CFBundleShortVersionString"), info.get("CFBundleVersion")
    require(isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", version), "Invalid app version")
    require(isinstance(build, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", build), "Invalid app build number")
    executable = info.get("CFBundleExecutable")
    require(isinstance(executable, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", executable)
            and (app / executable).is_file(), "App executable is missing or unsafe")
    extensions = list((app / "PlugIns").glob("*.appex"))
    require(len(extensions) == 1 and not extensions[0].is_symlink(), "Expected exactly one Trotter share extension")
    extension = extensions[0]
    ext_info = plist(extension / "Info.plist")
    require(ext_info.get("CFBundleIdentifier") == EXTENSION, "Unexpected embedded extension identifier")
    require(ext_info.get("CFBundleSupportedPlatforms") == [platform], "Share extension platform does not match the app")
    require(ext_info.get("CFBundleShortVersionString") == version and ext_info.get("CFBundleVersion") == build,
            "Share extension version/build does not match the app")
    require(ext_info.get("NSExtension", {}).get("NSExtensionPointIdentifier") == "com.apple.share-services",
            "Embedded extension is not an Instagram share destination")
    ext_executable = ext_info.get("CFBundleExecutable")
    require(isinstance(ext_executable, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", ext_executable)
            and (extension / ext_executable).is_file(), "Share extension executable is missing or unsafe")
    return {"app": str(app), "extension": str(extension), "bundle_id": BUNDLE,
            "version": version, "build": build, "executable": executable}


def api_origin(value):
    url = urlsplit(value)
    require(url.scheme == "https" and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment and not url.port and url.path in ("", "/")
            and url.hostname not in ("localhost", "127.0.0.1"), "A public HTTPS production API origin is required")
    return value.rstrip("/"), url.hostname


def validate_signed_target(info, entitlements, profile, certificate, expected, extension=False):
    team = expected["team_id"]
    prefix = expected.get("app_id_prefix") or team
    require(re.fullmatch(r"[A-Z0-9]{10}", team) and re.fullmatch(r"[A-Z0-9]{10}", prefix), "Invalid Apple team or App ID prefix")
    bundle = EXTENSION if extension else BUNDLE
    identifier = prefix + "." + bundle
    keychain = prefix + "." + BUNDLE + ".dreamshare"
    require(info.get("CFBundleIdentifier") == bundle, "Wrong signed target")
    require(profile.get("TeamIdentifier") == [team], "Provisioning profile belongs to another team")
    require(prefix in profile.get("ApplicationIdentifierPrefix", []), "Wrong provisioning App ID prefix")
    expiry = profile.get("ExpirationDate")
    require(isinstance(expiry, datetime), "Missing provisioning expiration")
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    require(expiry > datetime.now(timezone.utc), "Provisioning profile expired")
    require("ProvisionedDevices" not in profile and not profile.get("ProvisionsAllDevices"), "Profile is not App Store distribution")
    grants = profile.get("Entitlements", {})
    require(grants.get("application-identifier") == identifier and entitlements.get("application-identifier") == identifier,
            "Provisioned or signed app identifier does not match Trotter")
    require(entitlements.get("com.apple.developer.team-identifier") == team
            and grants.get("com.apple.developer.team-identifier") == team, "Signed/profile team does not match")
    require(not entitlements.get("get-task-allow") and not grants.get("get-task-allow"), "Production signing permits debugging")
    require(certificate in profile.get("DeveloperCertificates", []), "Actual signing certificate is not allowed by the provisioning profile")
    require(set(entitlements.get("com.apple.security.application-groups", [])) == {GROUP}
            and GROUP in grants.get("com.apple.security.application-groups", []), "Shared App Group missing or belongs to another app")
    signed_keychain = set(entitlements.get("keychain-access-groups", []))
    require(keychain in signed_keychain and signed_keychain <= {keychain, identifier}, "Unexpected or missing shared Keychain entitlement")
    allowed_keychains = grants.get("keychain-access-groups", [])
    require(all(group in allowed_keychains or prefix + ".*" in allowed_keychains for group in signed_keychain),
            "Profile does not permit the signed Keychain groups")
    require(info.get("TrotterShareKeychainGroup") == keychain, "Shared Keychain Info.plist prefix was not expanded correctly")
    if extension:
        require(not entitlements.get("com.apple.developer.associated-domains") and not entitlements.get("com.apple.developer.applesignin"),
                "Share extension unexpectedly inherits main-app sign-in/link capabilities")
    else:
        location_purpose = info.get("NSLocationWhenInUseUsageDescription")
        require(isinstance(location_purpose, str) and location_purpose.strip(),
                "Main app is missing NSLocationWhenInUseUsageDescription required by the linked map SDK")
        require(entitlements.get("com.apple.developer.applesignin") == ["Default"]
                and grants.get("com.apple.developer.applesignin") == ["Default"], "Sign in with Apple capability is missing")
        _, host = api_origin(expected["api_url"])
        domain = "applinks:" + host
        require(set(entitlements.get("com.apple.developer.associated-domains", [])) == {domain}, "Production invitation associated domain is missing or unexpected")
        require(domain in grants.get("com.apple.developer.associated-domains", [])
                or "*" in grants.get("com.apple.developer.associated-domains", []), "Profile does not permit invitation links")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("kind", choices=("zip", "tar")); extract.add_argument("archive"); extract.add_argument("destination")
    bundle = sub.add_parser("bundle")
    bundle.add_argument("kind", choices=("zip", "tar")); bundle.add_argument("root"); bundle.add_argument("platform")
    simulator = sub.add_parser("simulator-entitlements")
    simulator.add_argument("app")
    signed = sub.add_parser("signed")
    signed.add_argument("info"); signed.add_argument("entitlements"); signed.add_argument("profile"); signed.add_argument("certificate"); signed.add_argument("expected")
    signed.add_argument("--extension", action="store_true")
    args = parser.parse_args()
    if args.action == "extract":
        extract_archive(args.archive, args.destination, args.kind)
    elif args.action == "bundle":
        print(json.dumps(validate_bundle(find_app(args.root, args.kind), args.platform)))
    elif args.action == "simulator-entitlements":
        validate_simulator_entitlements(Path(args.app))
    else:
        with open(args.expected, encoding="utf-8") as source:
            expected = json.load(source)
        validate_signed_target(plist(args.info), plist(args.entitlements), plist(args.profile),
                               Path(args.certificate).read_bytes(), expected, args.extension)


def simulator_entitlements(executable):
    # Xcode embeds simulator entitlements in a Mach-O section. The ad hoc code
    # signature can legitimately contain an empty dictionary, so codesign alone
    # cannot detect the missing-Keychain-entitlement launch failure.
    data = Path(executable).read_bytes()
    require(len(data) >= 32 and data[:4] == b'\xcf\xfa\xed\xfe', "Expected a thin 64-bit simulator executable")
    commands, command_bytes = struct.unpack_from('<II', data, 16)
    end = 32 + command_bytes
    require(end <= len(data) and commands <= command_bytes // 8, "Invalid Mach-O load commands")
    cursor = 32
    for _ in range(commands):
        require(cursor + 8 <= end, "Truncated Mach-O load command")
        command, size = struct.unpack_from('<II', data, cursor)
        require(size >= 8 and cursor + size <= end, "Invalid Mach-O command size")
        if command == 0x19:
            require(size >= 72, "Truncated Mach-O segment")
            count = struct.unpack_from('<I', data, cursor + 64)[0]
            require(72 + count * 80 <= size, "Truncated Mach-O sections")
            for index in range(count):
                section = cursor + 72 + index * 80
                name = data[section:section + 16].rstrip(b'\0')
                segment = data[section + 16:section + 32].rstrip(b'\0')
                if name == b'__entitlements' and segment == b'__TEXT':
                    length = struct.unpack_from('<Q', data, section + 40)[0]
                    offset = struct.unpack_from('<I', data, section + 48)[0]
                    require(offset >= end and length > 0 and offset + length <= len(data), "Invalid simulator entitlements bounds")
                    value = plistlib.loads(data[offset:offset + length].rstrip(b'\0'))
                    require(isinstance(value, dict), "Invalid simulator entitlements")
                    return value
        cursor += size
    raise ValueError("Simulator entitlements are missing; build with Xcode ad hoc signing enabled")


def validate_simulator_entitlements(app):
    validate_bundle(app, 'iPhoneSimulator')
    shared_keychain = None
    for target, bundle in [(app, BUNDLE), (app / 'PlugIns' / 'TrotterShare.appex', EXTENSION)]:
        info = plist(target / 'Info.plist')
        entitlements = simulator_entitlements(target / info['CFBundleExecutable'])
        identifier = entitlements.get('application-identifier', '')
        require(identifier.endswith('.' + bundle), "Simulator app identifier is missing or incorrect")
        prefix = identifier[:-len(bundle)]
        keychain = prefix + BUNDLE + '.dreamshare'
        require(info.get('TrotterShareKeychainGroup') == keychain
                and keychain in entitlements.get('keychain-access-groups', []), "Simulator shared Keychain configuration is missing or mismatched")
        require(GROUP in entitlements.get('com.apple.security.application-groups', []), "Simulator App Group is missing")
        require(shared_keychain is None or shared_keychain == keychain, "Simulator targets have different Keychain prefixes")
        shared_keychain = keychain


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, plistlib.InvalidFileException, zipfile.BadZipFile, tarfile.TarError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
