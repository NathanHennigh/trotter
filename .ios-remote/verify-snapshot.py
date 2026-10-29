#!/usr/bin/env python3
"""Safely materialize the exact content snapshot chosen by the Windows caller."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import unicodedata


def verify_extract(archive, expected_id, destination):
    if not re.fullmatch(r"[a-f0-9]{64}", expected_id):
        raise ValueError("Invalid snapshot identity")
    destination = Path(destination)
    if destination.exists():
        # Snapshot source is immutable; never overwrite files or build output.
        raise ValueError("Snapshot destination already exists; use a new run directory")
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > 30000:
            raise ValueError("Too many archive entries")
        normalized = {}
        filesystem_names = set()
        for member in members:
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if member.isdir():
                name = name.rstrip("/")
            if name in ("", ".") and member.isdir():
                continue
            if "\\" in name or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
                raise ValueError("Unsafe snapshot path")
            if name in normalized or (not member.isfile() and not member.isdir()):
                raise ValueError("Duplicate, linked or special archive entry")
            # The default Mac filesystem compares names without case and may
            # normalize Unicode. Refuse aliases before writing any source.
            filesystem_name = unicodedata.normalize("NFD", name).casefold()
            if filesystem_name in filesystem_names:
                raise ValueError("Conflicting names on the Mac filesystem")
            filesystem_names.add(filesystem_name)
            if not (name == "source-manifest.json" or name == "mobile-v2" or name.startswith("mobile-v2/")):
                raise ValueError("Unexpected snapshot root")
            normalized[name] = member
        meta = normalized.get("source-manifest.json")
        if not meta or not meta.isfile() or meta.size > 8 * 1024 * 1024:
            raise ValueError("Missing snapshot manifest")
        manifest = json.load(source.extractfile(meta))
        files = manifest.get("files")
        if manifest.get("schemaVersion") != 1 or not isinstance(files, list):
            raise ValueError("Unsupported snapshot manifest")
        if any(not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
               or type(entry.get("size")) is not int or entry["size"] < 0 for entry in files):
            raise ValueError("Invalid source manifest entry")
        canonical = json.dumps({"schemaVersion": 1, "files": files}, separators=(",", ":"), ensure_ascii=False).encode()
        if hashlib.sha256(canonical).hexdigest() != expected_id or manifest.get("contentId") != expected_id:
            raise ValueError("Snapshot manifest hash does not match")
        names = [entry.get("path") for entry in files]
        if names != sorted(set(names)):
            raise ValueError("Unordered or duplicate source files")
        actual = {name for name, member in normalized.items() if member.isfile()}
        if actual != set(names) | {"source-manifest.json"}:
            raise ValueError("Archive contains unmanifested or missing files")
        if sum(entry.get("size", -1) for entry in files) > 2 * 1024 * 1024 * 1024:
            raise ValueError("Snapshot is unexpectedly large")
        for entry in files:
            name = entry["path"]
            if not name.startswith("mobile-v2/") or not re.fullmatch(r"[a-f0-9]{64}", entry.get("sha256", "")):
                raise ValueError("Invalid source manifest entry")
            member = normalized[name]
            if type(entry.get("size")) is not int or entry["size"] < 0 or member.size != entry["size"]:
                raise ValueError("Source length does not match")
            digest = hashlib.sha256()
            with source.extractfile(member) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                raise ValueError("Source content does not match")
        destination.mkdir(parents=True, mode=0o700)
        # All names and bytes have been validated before touching the destination.
        for name in ["source-manifest.json", *names]:
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(normalized[name]) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            target.chmod(0o600)
    return manifest


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise ValueError("Usage: verify-snapshot.py ARCHIVE DESTINATION CONTENT_ID")
        manifest = verify_extract(sys.argv[1], sys.argv[3], sys.argv[2])
        print(f"Verified {len(manifest['files'])} source files for snapshot {manifest['contentId']}")
    except Exception as error:
        print(f"Snapshot verification failed: {error}", file=sys.stderr)
        sys.exit(1)
