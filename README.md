# Android libmpv builds

The project produces media-kit Android native-library JARs. Dependency versions
and the four existing ABI targets remain defined in `buildscripts/include/depinfo.sh`
and `buildscripts/build.sh`.

## Publish a mobile candidate

Use **Actions → Android libmpv release → Run workflow** (`mobile-release.yml`).
Choose the reviewed branch/ref and provide:

- `release_tag`: a new tag such as `v1.1.9-android.1`. It must start with `v` and a
  digit and contain only ASCII letters, digits, `.`, `_`, or `-`. Invalid Git ref
  forms, existing tags and existing releases are rejected.
- `request_id`: optional caller correlation ID, empty or 1–64 ASCII letters,
  digits and hyphens. The run title contains this ID and the release tag, so an
  app orchestration run can identify this dispatch without guessing by time.

Only the **default** flavor is built. It builds all four ABIs through the existing
`bundle_default.sh`; full and encoders-gpl are not silently included. The legacy
`build.yaml` now runs fast validation on main pushes, PRs and manual requests,
so deploying or merging the automation does not start a second native build or
rewrite the old `vnext` release. Full/GPL maintenance builds remain explicit local
entry points (`bundle_full.sh`, `bundle_encoders-gpl.sh`).

Publication produces a **prerelease**, never an automatic stable/latest promotion:

```text
default-arm64-v8a.jar
default-armeabi-v7a.jar
default-x86_64.jar
default-x86.jar
SHA256SUMS
mobile-libmpv-manifest.json
```

The JAR paths inside each archive are `lib/<abi>/*.so`, including `libmpv.so` and
native helper libraries from the pinned helper APK. Debug symbols are retained
as a separate workflow artifact for 14 days, not added to the consumer contract.

`mobile-libmpv-manifest.json` contains:

```json
{
  "schema_version": 1,
  "platform": "android",
  "repository": "ha1o0/libmpv-android-video-build",
  "tag": "v1.1.9-android.1",
  "source_commit": "the exact 40-character dispatch commit SHA",
  "workflow_run_id": 123456789,
  "request_id": "caller-generated-uuid",
  "assets": [
    {
      "name": "default-arm64-v8a.jar",
      "sha256": "computed from the uploaded JAR",
      "size": 123,
      "md5": "computed for the existing media-kit Gradle consumer",
      "kind": "android-jar",
      "abi": "arm64-v8a"
    }
  ]
}
```

The real manifest contains all four assets. `SHA256SUMS` covers the four JARs and
manifest. The application updater should verify the manifest's repository,
platform, tag, workflow run ID, request ID and exact ABI set, then verify bytes
before replacing dependency references. Production manifests always include the
integer run ID; local fixture generation can omit it. Consumers must wait for
that precise run to complete successfully before integrating the release. SHA256 is the integrity check; MD5 exists for compatibility with the
current Gradle downloader, not as the release's security guarantee.

## Publication guarantees and failure handling

The validation and build jobs have read-only repository permission. Only the
publish job has `contents: write`; PR events cannot reach that job. Inputs enter
scripts through quoted environment variables, not interpolated shell source.
The build and publish checkout the dispatch's exact `github.sha`, and the new tag
is created explicitly at that SHA.

A read-only preflight rejects an existing tag/release before compilation. Publish
repeats that check, then creates the ref without force, closing the race between
validation and publication. Assets upload into a new draft, are rechecked, and
only then become a prerelease. No action deletes/replaces tags, releases, or
assets. A failed or ambiguous upload leaves an unpublished draft/tag for human
inspection; use a new release tag for the next run. Do not retry the publish job
expecting it to overwrite a partial release. This is an automation policy, not a
claim that repository administrators cannot edit releases manually.

The final `Android release status` job fails unless validation, build and publish
all succeed. External orchestration can inspect that workflow's terminal status;
there is no privileged `workflow_run` listener executing PR-controlled artifacts.
Each job has a bounded timeout, and runs for the same tag serialize without
cancelling one another.

## Toolchain and 16 KiB alignment

This automation keeps the existing media dependency versions: NDK
`25.2.9519653`, FFmpeg `6.0`, mpv `78d43740f52db817d98bcf24fb30a76ab6fa13ff`, and
media-kit-android-helper `42054e5d479f39ccbb0ae604862e2bcaf59b74c2`.
The pinned helper itself uses AGP `8.4.2`, Gradle `8.10.2`, compile/target SDK 35
and an explicit `max-page-size=16384` linker option. The helper patch fixes its
NDK to the same existing NDK and uses a private static C++ runtime, avoiding an
old NDK `libc++_shared.so` becoming an unaligned bundled dependency. It does not
change the helper's C ABI. The SDK installer explicitly installs that helper's
API 35 / build-tools 34 requirements alongside the existing native build SDK.

Before publication, every shared library is inspected as a little-endian ELF
`ET_DYN` with the expected ABI/class/machine and valid `PT_LOAD` segments. Every
64-bit library—including helper dependencies—must have at least **16 KiB** load
segment alignment; a 4 KiB library fails the release. 32-bit libraries retain the
4 KiB minimum. Unexpected archives, duplicate entries, symlinks, traversal paths,
wrong ABIs, malformed ELF data and missing libmpv are rejected.

These checks do not establish end-to-end 16 KiB Android compatibility. The final
app's AGP/APK/AAB packaging alignment, native runtime behavior and playback still
need validation on a 16 KiB emulator/device. The native build has **not** been run
as part of this local automation implementation; local tests use synthetic ELF
fixtures, and the helper patch was checked against its pinned source commit.
Existing dependency tag downloads and host build utilities are not a fully
hermetic/reproducible build; no claim is made that this work upgrades or audits
the entire codec dependency graph.

## Local validation

Python scripts and tests use only the standard library:

```sh
python3 -m unittest discover -s tests -v
bash -n buildscripts/bundle_default.sh buildscripts/build.sh buildscripts/include/download-sdk.sh

# After a real native build (substitute a real commit):
python3 scripts/mobile_release.py package --directory buildscripts/artifacts/default \
  --tag v1.1.9-android.1 --source-commit 0123456789012345678901234567890123456789
python3 scripts/mobile_release.py verify --directory buildscripts/artifacts/default \
  --tag v1.1.9-android.1 --source-commit 0123456789012345678901234567890123456789
```

`github_mobile_release.py` is intended for the GitHub workflow environment. Its
network/permission and no-overwrite behavior is exercised locally using a fake
API; tests do not publish or contact GitHub.
