#!/usr/bin/env python3
"""Validate default Android JARs and produce the mobile release contract."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile

REPOSITORY = "ha1o0/libmpv-android-video-build"
ABIS = {"arm64-v8a": (2, 183), "armeabi-v7a": (1, 40),
        "x86_64": (2, 62), "x86": (1, 3)}
MANIFEST = "mobile-libmpv-manifest.json"
CHECKSUMS = "SHA256SUMS"
MAX_LIBRARY_SIZE = 256 * 1024 * 1024


def native_sources():
    """Bind release provenance to the source archives consumed by this checkout."""
    return json.loads((Path(__file__).resolve().parents[1] / 'mobile-sources.json').read_text())


def validate_identity(tag, source_commit, request_id="", workflow_run_id=None):
    if not re.fullmatch(r"v[0-9][A-Za-z0-9._-]{0,126}", tag):
        raise ValueError("release_tag must start with v + digit and use only letters, digits, dot, underscore or hyphen")
    if ".." in tag or tag.endswith((".", ".lock")):
        raise ValueError("release_tag must also be a valid Git tag")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a full lowercase Git SHA")
    if request_id and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", request_id):
        raise ValueError("request_id must be empty or 1-64 letters, digits or hyphens")
    if workflow_run_id is not None and (type(workflow_run_id) is not int or workflow_run_id <= 0):
        raise ValueError("workflow_run_id must be a positive integer")


def validate_elf(data, abi):
    expected_class, expected_machine = ABIS[abi]
    if len(data) < 52 or data[:4] != b"\x7fELF" or data[4] != expected_class or data[5:7] != b"\x01\x01":
        raise ValueError(f"Invalid little-endian ELF for {abi}")
    if struct.unpack_from("<HH", data, 16) != (3, expected_machine):
        raise ValueError(f"ELF must be ET_DYN with the correct machine for {abi}")
    if expected_class == 2:
        if len(data) < 64:
            raise ValueError("Truncated ELF64 header")
        offset = struct.unpack_from("<Q", data, 32)[0]
        entry_size, count = struct.unpack_from("<HH", data, 54)
        minimum = 56
    else:
        offset = struct.unpack_from("<I", data, 28)[0]
        entry_size, count = struct.unpack_from("<HH", data, 42)
        minimum = 32
    if not count or entry_size < minimum or offset + entry_size * count > len(data):
        raise ValueError("Invalid ELF program header table")
    alignments = []
    for index in range(count):
        position = offset + entry_size * index
        if struct.unpack_from("<I", data, position)[0] != 1:  # PT_LOAD
            continue
        if expected_class == 2:
            file_offset, virtual, _, file_size, memory_size, alignment = struct.unpack_from("<QQQQQQ", data, position + 8)
        else:
            file_offset, virtual, _, file_size, memory_size, _, alignment = struct.unpack_from("<IIIIIII", data, position + 4)
        if file_size > memory_size or file_offset + file_size > len(data):
            raise ValueError("Invalid ELF load segment bounds")
        if alignment < 4096 or alignment & (alignment - 1):
            raise ValueError("Invalid ELF load segment alignment")
        if file_offset % alignment != virtual % alignment:
            raise ValueError("ELF offset and virtual address alignment differ")
        if expected_class == 2 and alignment < 16384:
            raise ValueError(f"{abi} shared library does not satisfy 16 KiB PT_LOAD alignment")
        alignments.append(alignment)
    if not alignments:
        raise ValueError("ELF has no loadable segment")
    return alignments


def inspect_jar(path, abi):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError(f"Invalid JAR file: {path}")
    libraries = {}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > 128 or sum(entry.file_size for entry in entries) > 512 * 1024 * 1024:
            raise ValueError("Unexpected JAR entry count")
        seen = set()
        for entry in entries:
            name = entry.filename
            parts = PurePosixPath(name).parts
            if name in seen or "\\" in name or name.startswith("/") or ".." in parts or "." in name.split("/"):
                raise ValueError(f"Unsafe or duplicate JAR entry: {name}")
            seen.add(name)
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Encrypted/link JAR entry: {name}")
            if entry.is_dir():
                if name not in ("lib/", f"lib/{abi}/"):
                    raise ValueError(f"Unexpected JAR directory: {name}")
                continue
            if len(parts) != 3 or parts[:2] != ("lib", abi) or not re.fullmatch(r"lib[A-Za-z0-9_.+-]+\.so", parts[2]):
                raise ValueError(f"Unexpected JAR payload or ABI: {name}")
            if not 0 < entry.file_size <= MAX_LIBRARY_SIZE:
                raise ValueError(f"Invalid library size: {name}")
            libraries[name] = validate_elf(archive.read(entry), abi)
    if f"lib/{abi}/libmpv.so" not in libraries:
        raise ValueError(f"Missing libmpv.so in {path.name}")
    return libraries


def asset_record(path, abi):
    inspect_jar(path, abi)
    digest = hashlib.sha256()
    legacy = hashlib.md5()  # Required by the existing media-kit Gradle consumer.
    size = 0
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
            legacy.update(data)
            size += len(data)
    return {"name": path.name, "sha256": digest.hexdigest(), "size": size,
            "md5": legacy.hexdigest(), "kind": "android-jar", "abi": abi}


def package_release(directory, tag, source_commit, request_id="", workflow_run_id=None):
    validate_identity(tag, source_commit, request_id, workflow_run_id)
    expected = {f"default-{abi}.jar" for abi in ABIS}
    actual = {path.name for path in directory.glob("*.jar")}
    if actual != expected:
        raise ValueError(f"Expected exactly four default ABI JARs; found {sorted(actual)}")
    assets = [asset_record(directory / f"default-{abi}.jar", abi) for abi in ABIS]
    manifest = {"schema_version": 1, "platform": "android", "repository": REPOSITORY,
                "tag": tag, "source_commit": source_commit, "native_sources": native_sources(),
                "request_id": request_id, "assets": assets}
    if workflow_run_id is not None:
        manifest["workflow_run_id"] = workflow_run_id
    manifest_path = directory / MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sums = [f"{asset['sha256']}  {asset['name']}" for asset in assets]
    sums.append(f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  {MANIFEST}")
    (directory / CHECKSUMS).write_text("\n".join(sums) + "\n", encoding="ascii")
    return manifest


def verify_release(directory, tag, source_commit, request_id="", workflow_run_id=None):
    validate_identity(tag, source_commit, request_id, workflow_run_id)
    manifest_path = directory / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {"schema_version": 1, "platform": "android", "repository": REPOSITORY,
                "tag": tag, "source_commit": source_commit, "native_sources": native_sources(),
                "request_id": request_id,
                "assets": [asset_record(directory / f"default-{abi}.jar", abi) for abi in ABIS]}
    if workflow_run_id is not None:
        expected["workflow_run_id"] = workflow_run_id
    if manifest != expected:
        raise ValueError("Manifest differs from validated JARs or dispatch identity")
    expected_files = {asset["name"] for asset in manifest["assets"]} | {MANIFEST, CHECKSUMS}
    if {path.name for path in directory.iterdir()} != expected_files:
        raise ValueError("Release directory has missing or unexpected assets")
    sums = [f"{asset['sha256']}  {asset['name']}" for asset in manifest["assets"]]
    sums.append(f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  {MANIFEST}")
    if (directory / CHECKSUMS).read_text(encoding="ascii") != "\n".join(sums) + "\n":
        raise ValueError("SHA256SUMS differs from release assets")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["identity", "package", "verify"])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--request-id", default="")
    parser.add_argument("--workflow-run-id", type=int, default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--directory", type=Path, default=Path("buildscripts/artifacts/default"))
    args = parser.parse_args()
    validate_identity(args.tag, args.source_commit, args.request_id, args.workflow_run_id)
    if args.command == "package":
        package_release(args.directory, args.tag, args.source_commit, args.request_id, args.workflow_run_id)
    elif args.command == "verify":
        verify_release(args.directory, args.tag, args.source_commit, args.request_id, args.workflow_run_id)
    print(f"Validated Android {args.command}: {args.tag} at {args.source_commit}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        raise SystemExit(str(error)) from error
