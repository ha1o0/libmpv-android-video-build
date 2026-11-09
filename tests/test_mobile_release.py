import hashlib
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mobile_release as release
import github_mobile_release as publisher

TAG = "v1.1.9-android.1"
SHA = "a" * 40


def elf(abi, alignment=16384):
    bits, machine = release.ABIS[abi]
    data = bytearray(256)
    data[:7] = b"\x7fELF" + bytes([bits, 1, 1])
    struct.pack_into("<HHI", data, 16, 3, machine, 1)
    if bits == 2:
        struct.pack_into("<Q", data, 32, 64)
        struct.pack_into("<HH", data, 54, 56, 1)
        struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 256, 256, alignment)
    else:
        struct.pack_into("<I", data, 28, 52)
        struct.pack_into("<HH", data, 42, 32, 1)
        struct.pack_into("<IIIIIIII", data, 52, 1, 0, 0, 0, 256, 256, 5, alignment)
    return bytes(data)


def jar(directory, abi, entries=None):
    path = directory / f"default-{abi}.jar"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("lib/", b"")
        archive.writestr(f"lib/{abi}/", b"")
        for name, data in entries or [(f"lib/{abi}/libmpv.so", elf(abi)),
                                     (f"lib/{abi}/libmediakitandroidhelper.so", elf(abi))]:
            archive.writestr(name, data)
    return path


class FakeGitHub:
    def __init__(self, existing_tag=False, existing_release=False, upload_failure=None):
        self.calls = []
        self.existing_tag = existing_tag
        self.existing_release = existing_release
        self.uploads = []
        self.upload_failure = upload_failure

    def request(self, method, path, payload=None, content=None, filename=None):
        self.calls.append((method, path, payload, filename))
        if method == "GET" and path.startswith("/git/ref/"):
            return {} if self.existing_tag else None
        if method == "GET" and path.startswith("/releases/tags/"):
            return {} if self.existing_release else None
        if method == "POST" and path == "/git/refs":
            return {"ref": payload["ref"]}
        if method == "POST" and path == "/releases":
            return {"id": 1}
        if method == "POST" and filename:
            if self.upload_failure == filename:
                raise RuntimeError("Upload failed")
            asset = {"name": filename, "size": len(content), "state": "uploaded",
                     "digest": "sha256:" + hashlib.sha256(content).hexdigest()}
            self.uploads.append(asset)
            return asset
        if method == "GET" and path == "/releases/1/assets":
            return self.uploads
        if method == "PATCH":
            return {"draft": False, "prerelease": True, "html_url": "https://github.com/example/release"}
        raise AssertionError((method, path))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for abi in release.ABIS:
            jar(self.directory, abi)

    def test_rejects_native_source_provenance_mismatch(self):
        manifest = self.package()
        manifest['native_sources']['mpv']['commit'] = 'b' * 40
        (self.directory / release.MANIFEST).write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            release.verify_release(self.directory, TAG, SHA)

    def package(self):
        return release.package_release(self.directory, TAG, SHA)

    def test_contract_is_computed_from_actual_jars(self):
        manifest = self.package()
        self.assertEqual(manifest["repository"], release.REPOSITORY)
        self.assertEqual(manifest["platform"], "android")
        self.assertEqual(manifest["source_commit"], SHA)
        self.assertEqual({a["abi"] for a in manifest["assets"]}, set(release.ABIS))
        for asset in manifest["assets"]:
            data = (self.directory / asset["name"]).read_bytes()
            self.assertEqual(asset["size"], len(data))
            self.assertEqual(asset["md5"], hashlib.md5(data).hexdigest())
            self.assertEqual(asset["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(release.verify_release(self.directory, TAG, SHA), manifest)
        self.assertEqual(len((self.directory / release.CHECKSUMS).read_text().splitlines()), 5)

    def test_dispatch_identity_is_bound_to_manifest_and_cannot_be_swapped(self):
        manifest = release.package_release(self.directory, TAG, SHA, "req-123", 12345)
        self.assertEqual(manifest["request_id"], "req-123")
        self.assertEqual(manifest["workflow_run_id"], 12345)
        release.verify_release(self.directory, TAG, SHA, "req-123", 12345)
        for request_id, run_id in [("other", 12345), ("req-123", 56789), ("", None)]:
            with self.assertRaises(ValueError):
                release.verify_release(self.directory, TAG, SHA, request_id, run_id)
        for invalid in [0, -1, True, "123"]:
            with self.assertRaises(ValueError): release.validate_identity(TAG, SHA, "", invalid)

    def test_rejects_missing_or_additional_abi_jars(self):
        (self.directory / "default-x86.jar").unlink()
        with self.assertRaises(ValueError): self.package()
        jar(self.directory, "x86")
        (self.directory / "full-x86.jar").write_bytes(b"extra")
        with self.assertRaises(ValueError): self.package()

    def test_rejects_archive_without_libmpv(self):
        jar(self.directory, "arm64-v8a", [("lib/arm64-v8a/libother.so", elf("arm64-v8a"))])
        with self.assertRaisesRegex(ValueError, "Missing libmpv"): self.package()

    def test_rejects_wrong_abi_and_wrong_elf_machine(self):
        jar(self.directory, "arm64-v8a", [("lib/x86/libmpv.so", elf("x86"))])
        with self.assertRaises(ValueError): self.package()
        jar(self.directory, "arm64-v8a", [("lib/arm64-v8a/libmpv.so", elf("x86_64"))])
        with self.assertRaises(ValueError): self.package()

    def test_every_64_bit_library_requires_16k_alignment(self):
        for abi in ("arm64-v8a", "x86_64"):
            with self.subTest(abi=abi):
                jar(self.directory, abi, [(f"lib/{abi}/libmpv.so", elf(abi)),
                    (f"lib/{abi}/libc++_shared.so", elf(abi, 4096))])
                with self.assertRaisesRegex(ValueError, "16 KiB"): self.package()
                jar(self.directory, abi)

    def test_32_bit_four_k_alignment_is_retained(self):
        for abi in ("armeabi-v7a", "x86"):
            jar(self.directory, abi, [(f"lib/{abi}/libmpv.so", elf(abi, 4096))])
        self.package()

    def test_rejects_unloadable_or_truncated_elf(self):
        values = [b"not an ELF", elf("arm64-v8a")[:60]]
        missing_segment = bytearray(elf("arm64-v8a"))
        struct.pack_into("<I", missing_segment, 64, 0)
        values.append(bytes(missing_segment))
        for value in values:
            with self.subTest(value=value[:8]):
                jar(self.directory, "arm64-v8a", [("lib/arm64-v8a/libmpv.so", value)])
                with self.assertRaises(ValueError): self.package()

    def test_rejects_escape_paths_symlinks_and_duplicate_entries(self):
        for name in ("../libmpv.so", "/lib/arm64-v8a/libmpv.so", "lib\\arm64-v8a\\libmpv.so"):
            with self.subTest(name=name):
                jar(self.directory, "arm64-v8a", [(name, elf("arm64-v8a"))])
                with self.assertRaises(ValueError): self.package()
        path = jar(self.directory, "arm64-v8a")
        entry = zipfile.ZipInfo("lib/arm64-v8a/liblink.so")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(path, "a") as archive: archive.writestr(entry, "libmpv.so")
        with self.assertRaises(ValueError): self.package()
        path = jar(self.directory, "arm64-v8a")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(path, "a") as archive:
                archive.writestr("lib/arm64-v8a/libmpv.so", elf("arm64-v8a"))
        with self.assertRaises(ValueError): self.package()

    def test_identity_rejects_shell_and_git_ref_metacharacters(self):
        for value in ("latest", "v1;echo", "v1$(touch x)", "v1/a", "v1..2", "v1.lock", "v1.", "v1\n"):
            with self.subTest(tag=value), self.assertRaises(ValueError):
                release.validate_identity(value, SHA)
        for value in ("a" * 7, "g" * 40, "A" * 40):
            with self.assertRaises(ValueError): release.validate_identity(TAG, value)
        for value in ("x/1", "x y", "x" * 65, "x\n"):
            with self.assertRaises(ValueError): release.validate_identity(TAG, SHA, value)
        release.validate_identity(TAG, SHA, "abc-123")

    def test_verify_detects_tampering(self):
        self.package()
        path = self.directory / "default-x86.jar"
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("lib/x86/libextra.so", elf("x86"))
        with self.assertRaisesRegex(ValueError, "Manifest differs"):
            release.verify_release(self.directory, TAG, SHA)
        self.package()
        (self.directory / release.CHECKSUMS).write_text("wrong")
        with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
            release.verify_release(self.directory, TAG, SHA)

    def test_publish_uses_exact_sha_and_publishes_only_after_all_uploads(self):
        release.package_release(self.directory, TAG, SHA, "request-1", 123)
        api = FakeGitHub()
        result = publisher.publish(api, self.directory, TAG, SHA, "request-1", 123)
        writes = [call for call in api.calls if call[0] != "GET"]
        self.assertEqual(writes[0], ("POST", "/git/refs", {"ref": "refs/tags/" + TAG, "sha": SHA}, None))
        self.assertEqual(writes[1][2]["target_commitish"], SHA)
        self.assertTrue(writes[1][2]["draft"])
        self.assertTrue(writes[1][2]["prerelease"])
        self.assertEqual(len(api.uploads), 6)
        self.assertEqual(writes[-1][0], "PATCH")
        self.assertEqual(result["draft"], False)
        self.assertEqual(result["prerelease"], True)

    def test_existing_tag_or_release_never_receives_writes(self):
        self.package()
        for api in [FakeGitHub(existing_tag=True), FakeGitHub(existing_release=True)]:
            with self.assertRaises(ValueError): publisher.publish(api, self.directory, TAG, SHA)
            self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_upload_failure_preserves_unpublished_draft_without_deletion(self):
        self.package()
        api = FakeGitHub(upload_failure="default-x86_64.jar")
        with self.assertRaises(RuntimeError): publisher.publish(api, self.directory, TAG, SHA)
        self.assertFalse(any(call[0] in ("PATCH", "DELETE") for call in api.calls))

    def test_pinned_helper_patch_applies_and_keeps_existing_platform_versions(self):
        root = Path(__file__).resolve().parents[1]
        helper = self.directory / "helper"
        (helper / "app").mkdir(parents=True)
        original = (root / "tests/fixtures/helper-app-build.gradle").read_bytes()
        (helper / "app/build.gradle").write_bytes(original)
        patch = root / "buildscripts/patches/media-kit-android-helper/native-toolchain.patch"
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=helper, check=True, capture_output=True)
        subprocess.run(["git", "apply", str(patch)], cwd=helper, check=True, capture_output=True)
        result = (helper / "app/build.gradle").read_text()
        self.assertIn("compileSdk 35", result)
        self.assertIn("targetSdk 35", result)
        self.assertIn("minSdk 21", result)
        self.assertIn("ndkVersion '25.2.9519653'", result)
        self.assertIn("arguments '-DANDROID_STL=c++_static'", result)
        self.assertIn("signingConfig signingConfigs.debug", result)

    def test_ref_race_cannot_update_or_publish_existing_tag(self):
        self.package()
        class RacedGitHub(FakeGitHub):
            def request(self, method, path, **kwargs):
                if method == "POST" and path == "/git/refs":
                    self.calls.append((method, path, kwargs.get("payload"), None))
                    raise RuntimeError("GitHub ref already exists")
                return super().request(method, path, **kwargs)
        api = RacedGitHub()
        with self.assertRaises(RuntimeError): publisher.publish(api, self.directory, TAG, SHA)
        self.assertFalse(any(call[1] == "/releases" or call[0] in ("PATCH", "DELETE") for call in api.calls))

    def test_upload_checksum_mismatch_never_publishes_draft(self):
        self.package()
        class CorruptUpload(FakeGitHub):
            def request(self, method, path, **kwargs):
                result = super().request(method, path, **kwargs)
                if kwargs.get("filename") == release.MANIFEST:
                    result["digest"] = "sha256:" + "0" * 64
                return result
        api = CorruptUpload()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            publisher.publish(api, self.directory, TAG, SHA)
        self.assertFalse(any(call[0] in ("PATCH", "DELETE") for call in api.calls))

    def test_invalid_assets_fail_before_any_remote_operation(self):
        self.package()
        (self.directory / "unexpected.txt").write_text("extra")
        api = FakeGitHub()
        with self.assertRaises(ValueError): publisher.publish(api, self.directory, TAG, SHA)
        self.assertEqual(api.calls, [])


if __name__ == "__main__": unittest.main()
